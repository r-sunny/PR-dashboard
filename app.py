import json
import os
import pickle
from datetime import datetime

import streamlit as st
import pandas as pd
import requests
from dateutil.parser import parse


# ================== CONFIG ==================

CONFIG_FILE = "config.json"
CACHE_DATA_FILE = "last_run_data.pkl"
CACHE_META_FILE = "last_run_meta.json"

with open(CONFIG_FILE) as f:
    config = json.load(f)

gl_cfg = config["gitlab"]
th = config["thresholds"]


# ================== GITLAB CLIENT ==================

class GitLabClient:
    def __init__(self, base_url, pat):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"PRIVATE-TOKEN": pat})

    def _get(self, path, params=None):
        url = f"{self.base_url}/api/v4{path}"
        r = self.session.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def get_top_level_groups(self):
        return self._get("/groups", {"top_level_only": True, "per_page": 100})

    def get_subgroups(self, group_id):
        return self._get(f"/groups/{group_id}/subgroups", {"per_page": 100})

    def get_projects(self, group_id):
        return self._get(f"/groups/{group_id}/projects", {"per_page": 100})

    def get_merge_requests(self, project_id, states):
        mrs = []
        for state in states:
            mrs.extend(
                self._get(
                    f"/projects/{project_id}/merge_requests",
                    {"state": state, "per_page": 100}
                )
            )
        return mrs

    def get_diff_stats(self, project_id, mr_iid):
        data = self._get(
            f"/projects/{project_id}/merge_requests/{mr_iid}/changes"
        )
        return data.get("changes_count", 0)

    def get_user_comments_count(self, project_id, mr_iid):
        notes = self._get(
            f"/projects/{project_id}/merge_requests/{mr_iid}/notes",
            {"per_page": 100}
        )
        return sum(1 for n in notes if not n.get("system", False))


# ================== LOGIC ==================

def calculate_days_past(mr):
    created = parse(mr["created_at"]).replace(tzinfo=None)

    if mr["state"] == "opened":
        end = datetime.utcnow()
    elif mr.get("merged_at"):
        end = parse(mr["merged_at"]).replace(tzinfo=None)
    elif mr.get("closed_at"):
        end = parse(mr["closed_at"]).replace(tzinfo=None)
    else:
        end = datetime.utcnow()

    return max((end - created).days, 0)


def calculate_score(days_past, lines_changed, comments):
    lines_changed_for_denominator = 0

    if days_past < 1:
        days_past = 1

    if lines_changed == 1:
        lines_changed_for_denominator = 1.05

    numerator = (
        (days_past * th["days_threshold"])
        + (lines_changed * th["lines_changed_threshold"])
    )

    denominator = (
            (days_past * th["days_threshold"])
            * lines_changed_for_denominator
            + ((comments * th["comment_threshold"]) + 1)
    )

    if denominator == 0:
        return 0

    return int((numerator / denominator) * 100)


# ================== CACHE ==================

def load_cached_data():
    with open(CACHE_DATA_FILE, "rb") as f:
        return pickle.load(f)

def save_cached_data(df):
    with open(CACHE_DATA_FILE, "wb") as f:
        pickle.dump(df, f)
    with open(CACHE_META_FILE, "w") as f:
        json.dump({"last_run": datetime.utcnow().isoformat()}, f)

def get_last_run_time():
    if not os.path.exists(CACHE_META_FILE):
        return None
    with open(CACHE_META_FILE) as f:
        return json.load(f).get("last_run")


# ================== UI ==================

st.set_page_config(layout="wide")
st.markdown("<style>div.block-container{padding-top:1.2rem;}</style>", unsafe_allow_html=True)

client = GitLabClient(gl_cfg["base_url"], gl_cfg["pat"])

if "stage" not in st.session_state:
    st.session_state.stage = "init"


# ---------- STAGE 1 : RUN / LOAD ----------

if st.session_state.stage == "init":
    st.header("GitLab PR Dashboard")

    last_run = get_last_run_time()
    if last_run and os.path.exists(CACHE_DATA_FILE):
        st.info(f"Last run: {datetime.fromisoformat(last_run).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        st.session_state.use_cached = (
            st.radio("Choose an option", ["Load previous data", "Re-run"])
            == "Load previous data"
        )
    else:
        st.warning("No previous run found. Data will be fetched.")
        st.session_state.use_cached = False

    if st.button("Continue"):
        st.session_state.stage = "select"
        st.rerun()


# ---------- STAGE 2 : SELECTION ----------

if st.session_state.stage == "select":
    st.subheader("Select Scope")

    groups = client.get_top_level_groups()
    group_map = {g["name"]: g["id"] for g in groups}

    group_name = st.selectbox("Group", list(group_map.keys()))
    group_id = group_map[group_name]

    subgroups = client.get_subgroups(group_id)
    subgroup_id = None

    if subgroups:
        subgroup_map = {sg["name"]: sg["id"] for sg in subgroups}
        subgroup_name = st.selectbox("Subgroup", list(subgroup_map.keys()))
        subgroup_id = subgroup_map[subgroup_name]

    target_group = subgroup_id or group_id

    projects = client.get_projects(target_group)
    project_map = {p["name"]: p["id"] for p in projects}

    project_name = st.selectbox("Project", list(project_map.keys()))

    if st.button("Load Merge Requests"):
        st.session_state.project_id = project_map[project_name]
        st.session_state.stage = "data"
        st.rerun()


if st.session_state.stage == "data":
    if st.session_state.use_cached:
        df = load_cached_data()
    else:
        mrs = client.get_merge_requests(
            st.session_state.project_id,
            gl_cfg["fetch_mr_states"]
        )

        rows = []
        for mr in mrs:
            title = mr["title"]
            rows.append({
                "ID": mr["iid"],
                "Title": title[:40] + "..." if len(title) > 40 else title,
                "URL": mr["web_url"],
                "State": "Assigned" if mr.get("assignees") else "Unassigned",
                "Assignee": ", ".join(a["name"] for a in mr.get("assignees", [])) or "-",
                "Score": calculate_score(
                    calculate_days_past(mr),
                    client.get_diff_stats(st.session_state.project_id, mr["iid"]),
                    client.get_user_comments_count(st.session_state.project_id, mr["iid"])
                )
            })

        df = pd.DataFrame(rows)
        save_cached_data(df)

    st.subheader("Merge Requests")
    st.dataframe(df, use_container_width=True)
