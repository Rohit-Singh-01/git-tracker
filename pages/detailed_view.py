
import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime
from dateutil import parser
from io import BytesIO
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import altair as alt

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]

# Initialize session state
if "user_data" not in st.session_state:
    st.session_state.user_data = None
if "projects_data" not in st.session_state:
    st.session_state.projects_data = None
if "commits_data" not in st.session_state:
    st.session_state.commits_data = None
if "merge_requests_data" not in st.session_state:
    st.session_state.merge_requests_data = None
if "issues_data" not in st.session_state:
    st.session_state.issues_data = None
if "last_username" not in st.session_state:
    st.session_state.last_username = ""


# --- API FETCH FUNCTIONS ---
async def fetch_json(session, url, params=None):
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    async with session.get(url, headers=headers, params=params) as response:
        if response.status == 401:
            raise Exception("❌ Unauthorized: Check your GitLab token or permissions.")
        response.raise_for_status()
        return await response.json()


async def fetch_user(session, username):
    users = await fetch_json(
        session, f"{BASE_URL}/users", params={"username": username}
    )
    return users[0] if users else None


async def fetch_projects(session, user_id):
    return await fetch_json(session, f"{BASE_URL}/users/{user_id}/projects")


async def fetch_commits(session, project_id, user_email):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/repository/commits",
        params={"author_email": user_email},
    )


async def fetch_merge_requests(session, user_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/merge_requests",
        params={"author_id": user_id, "scope": "all"},
    )


async def fetch_user_issues(session, user_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/issues",
        params={"author_id": user_id, "scope": "all", "per_page": 100},
    )


async def fetch_project_issues_by_author(session, project_id, user_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/issues",
        params={"author_id": user_id, "per_page": 100},
    )


# --- PDF EXPORT FUNCTION ---
def export_df_to_pdf(df, title="Report"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    pdf.cell(200, 10, text=title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(5)

    if df.empty:
        pdf.cell(
            200,
            10,
            text="No data available",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align="C",
        )
    else:
        col_width = pdf.w / (len(df.columns) + 1)
        for header in df.columns:
            pdf.cell(col_width, 10, str(header), border=1)
        pdf.ln()

        for _, row in df.iterrows():
            for value in row:
                pdf.cell(col_width, 10, str(value)[:30], border=1)
            pdf.ln()

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer


# --- MAIN GATHER FUNCTION ---
async def gather_data(username):
    async with aiohttp.ClientSession() as session:
        user = await fetch_user(session, username)
        if not user:
            raise ValueError("User not found!")

        user_id = user["id"]
        user_email = user.get("public_email") or user.get("email", "")
        projects = await fetch_projects(session, user_id)

        commits_by_project = {}
        issues = []

        for project in projects:
            project_id = project["id"]
            project_name = project["name_with_namespace"]
            commits = await fetch_commits(session, project_id, user_email)
            commits_by_project[project_name] = commits

        try:
            issues = await fetch_user_issues(session, user_id)
            st.info(f"✅ Found {len(issues)} issues using global user query")
        except Exception as e:
            st.warning(f"⚠️ Global issue fetch failed: {str(e)}")
            issues = []
            for project in projects:
                try:
                    project_issues = await fetch_project_issues_by_author(
                        session, project["id"], user_id
                    )
                    issues.extend(project_issues)
                except Exception as project_error:
                    st.warning(
                        f"⚠️ Failed to fetch issues from {project['name']}: {str(project_error)}"
                    )
            st.info(f"✅ Found {len(issues)} issues using project-based query")

        merge_requests = await fetch_merge_requests(session, user_id)

        return user, projects, commits_by_project, merge_requests, issues


# --- STREAMLIT UI ---
st.title("📊 GitLab Contribution Dashboard")
username = st.text_input("Enter GitLab Username", value=st.session_state.last_username)

# Check if we need to fetch new data
need_fetch = username and (
    username != st.session_state.last_username or st.session_state.user_data is None
)

if username and need_fetch:
    with st.spinner("Fetching user data..."):
        try:
            user, projects, commits_by_project, merge_requests, issues = asyncio.run(
                gather_data(username)
            )

            # Store in session state
            st.session_state.user_data = user
            st.session_state.projects_data = projects
            st.session_state.commits_data = commits_by_project
            st.session_state.merge_requests_data = merge_requests
            st.session_state.issues_data = issues
            st.session_state.last_username = username

        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.error(
                "Please check your GitLab token, permissions, and base URL configuration."
            )

# Display data if available in session state
if username and st.session_state.user_data:
    user = st.session_state.user_data
    projects = st.session_state.projects_data
    commits_by_project = st.session_state.commits_data
    merge_requests = st.session_state.merge_requests_data
    issues = st.session_state.issues_data

    st.subheader(f"👤 User: {user['name']} ({user['username']})")
    st.write(f"📧 Email: {user.get('public_email', 'Not public')}")

    show_commits = st.checkbox("Show Commits", value=True)
    show_mrs = st.checkbox("Show Merge Requests", value=True)
    show_issues = st.checkbox("Show Issues", value=True)

    project_names = list(commits_by_project.keys())
    selected_project = st.selectbox("📁 Filter by Project", ["All"] + project_names)

    min_date, max_date = datetime(2000, 1, 1), datetime.now()
    date_range = st.date_input("📅 Filter by Date Range", [min_date, max_date])
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    elif hasattr(date_range, "__len__") and len(date_range) == 2:
        start_date, end_date = date_range[0], date_range[1]
    else:
        start_date = end_date = date_range

    time_unit = st.selectbox("📊 Visualize by", ["Day", "Month", "Year"])

    def get_time_group_column(df, col):
        df[col] = pd.to_datetime(df[col], errors="coerce")
        if time_unit == "Day":
            # Format as DD-MM-YYYY for display
            return df[col].dt.strftime("%d-%m-%Y")
        elif time_unit == "Month":
            return df[col].dt.to_period("M").astype(str)
        elif time_unit == "Year":
            return df[col].dt.year

    if show_commits:
        st.subheader("📝 Commits by Project")
        for project_name, commits in commits_by_project.items():
            if selected_project != "All" and project_name != selected_project:
                continue
            if not commits:
                continue

            df_commits = pd.DataFrame(
                [
                    {
                        "Message": c["title"],
                        "Date": parser.parse(c["created_at"]).strftime("%Y-%m-%d"),
                        "Time": parser.parse(c["created_at"]).strftime("%H:%M:%S"),
                        "Link": c.get("web_url", ""),
                    }
                    for c in commits
                ]
            )
            df_commits = df_commits[
                (pd.to_datetime(df_commits["Date"]) >= pd.to_datetime(start_date))
                & (pd.to_datetime(df_commits["Date"]) <= pd.to_datetime(end_date))
            ]
            if not df_commits.empty:
                st.markdown(f"**{project_name}** ({len(df_commits)} commits)")
                st.dataframe(df_commits, use_container_width=True)

                # Create grouped data for chart
                grouped = df_commits.copy()
                grouped["Group"] = get_time_group_column(grouped, "Date")
                count_by_group = (
                    grouped.groupby("Group").size().reset_index(name="Commits")
                )

                # Sort by date for proper ordering (especially important for days)
                if time_unit == "Day":
                    # Convert back to datetime for sorting, then format for display
                    count_by_group["sort_date"] = pd.to_datetime(
                        count_by_group["Group"], format="%d-%m-%Y"
                    )
                    count_by_group = count_by_group.sort_values("sort_date")
                    count_by_group = count_by_group.drop("sort_date", axis=1)

                chart = (
                    alt.Chart(count_by_group)
                    .mark_bar()
                    .encode(
                        x=alt.X("Group:O", title=time_unit, sort=None),
                        y=alt.Y("Commits:Q", title="Number of Commits"),
                        tooltip=["Group", "Commits"],
                    )
                    .properties(
                        title=f"{project_name} - Commits by {time_unit}",
                        width=600,
                        height=400,
                    )
                )
                st.altair_chart(chart, use_container_width=True)

    if show_mrs and merge_requests:
        st.subheader("🔀 Merge Requests")
        df_mrs = pd.DataFrame(
            [
                {
                    "Title": mr["title"],
                    "State": mr["state"],
                    "Created": parser.parse(mr["created_at"]).strftime("%Y-%m-%d"),
                    "Link": mr.get("web_url", ""),
                }
                for mr in merge_requests
            ]
        )
        df_mrs = df_mrs[
            (pd.to_datetime(df_mrs["Created"]) >= pd.to_datetime(start_date))
            & (pd.to_datetime(df_mrs["Created"]) <= pd.to_datetime(end_date))
        ]
        if not df_mrs.empty:
            st.dataframe(df_mrs, use_container_width=True)

    if show_issues and issues:
        st.subheader("🐛 Issues")
        df_issues = pd.DataFrame(
            [
                {
                    "Title": issue["title"],
                    "State": issue["state"],
                    "Created": parser.parse(issue["created_at"]).strftime("%Y-%m-%d"),
                    "Link": issue.get("web_url", ""),
                }
                for issue in issues
            ]
        )
        df_issues = df_issues[
            (pd.to_datetime(df_issues["Created"]) >= pd.to_datetime(start_date))
            & (pd.to_datetime(df_issues["Created"]) <= pd.to_datetime(end_date))
        ]
        if not df_issues.empty:
            st.dataframe(df_issues, use_container_width=True)

elif username and not st.session_state.user_data and not need_fetch:
    st.info("Enter a username to fetch GitLab data")
