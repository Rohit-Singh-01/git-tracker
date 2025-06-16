
import streamlit as st
import asyncio
import aiohttp
import pandas as pd
import numpy as np
from datetime import date
from dateutil import parser
import io
import hashlib

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]

# --- PERSISTENT SESSION STATE INIT ---
# Use a unique key prefix to ensure persistence across pages
STATE_PREFIX = "gitlab_tracker_"

def init_persistent_state():
    """Initialize session state variables that persist across pages"""
    state_vars = {
        f"{STATE_PREFIX}fetched_data": None,
        f"{STATE_PREFIX}csv_data": None,
        f"{STATE_PREFIX}last_fetch_params": None,
        f"{STATE_PREFIX}data_hash": None
    }
    
    for key, default_value in state_vars.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# Initialize persistent state
init_persistent_state()

# --- CACHING FUNCTIONS ---
@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_user_cached(username):
    """Cached wrapper for user fetching"""
    return asyncio.run(_fetch_user_async(username))

@st.cache_data(ttl=1800)  # Cache for 30 minutes
def gather_user_data_cached(username, start_date_str, end_date_str):
    """Cached wrapper for user data gathering"""
    start_date = parser.parse(start_date_str).date()
    end_date = parser.parse(end_date_str).date()
    return asyncio.run(gather_user_data(username, start_date, end_date))

@st.cache_data(ttl=3600)
def process_csv_data_cached(csv_content_hash, usernames, start_date_str, end_date_str):
    """Cached processing of CSV data"""
    start_date = parser.parse(start_date_str).date()
    end_date = parser.parse(end_date_str).date()
    
    all_data = []
    for username in usernames:
        try:
            user_data = asyncio.run(gather_user_data(username, start_date, end_date))
            if user_data:
                all_data.append(user_data)
        except Exception as e:
            st.warning(f"Failed to fetch data for {username}: {str(e)}")
    
    return all_data

def get_data_hash(usernames, start_date, end_date):
    """Generate hash for caching purposes"""
    data_string = f"{','.join(sorted(usernames))}{start_date}{end_date}"
    return hashlib.md5(data_string.encode()).hexdigest()

# --- API FETCH FUNCTIONS ---
async def fetch_json(session, url, params=None):
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    async with session.get(url, headers=headers, params=params) as response:
        response.raise_for_status()
        return await response.json()

async def _fetch_user_async(username):
    """Internal async function for user fetching"""
    async with aiohttp.ClientSession() as session:
        users = await fetch_json(
            session, f"{BASE_URL}/users", params={"username": username}
        )
        return users[0] if users else None

async def fetch_user_projects(session, user_id):
    return await fetch_json(session, f"{BASE_URL}/users/{user_id}/projects")

async def fetch_contributed_projects(session, user_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/users/{user_id}/contributed_projects",
        params={"per_page": 100},
    )

async def fetch_commits(session, project_id, user_email):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/repository/commits",
        params={"author_email": user_email},
    )

async def fetch_merge_requests(session, user_id, project_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/merge_requests",
        params={"author_id": user_id, "state": "all"},  # Get all states
    )

async def fetch_issues(session, user_id, project_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/issues",
        params={"author_id": user_id, "state": "all"},  # Get all states
    )

async def fetch_issue_comments(session, project_id, issue_iid):
    return await fetch_json(
        session, f"{BASE_URL}/projects/{project_id}/issues/{issue_iid}/notes"
    )

async def fetch_mr_comments(session, project_id, mr_iid):
    return await fetch_json(
        session, f"{BASE_URL}/projects/{project_id}/merge_requests/{mr_iid}/notes"
    )

# --- COUNT HELPER ---
def count_items_by_date(items, date_field, start_date, end_date):
    """Fixed date counting with better error handling"""
    count = 0
    for item in items:
        try:
            if date_field in item and item[date_field] is not None:
                # Handle different date formats
                date_str = item[date_field]
                if isinstance(date_str, str) and date_str.strip():
                    item_date = parser.parse(date_str).date()
                    if start_date <= item_date <= end_date:
                        count += 1
        except (ValueError, TypeError, AttributeError) as e:
            # Skip items with invalid dates
            continue
    return count

def count_items_by_date_and_state(items, date_field, start_date, end_date, state_filter=None):
    """Count items by date range and optionally by state"""
    count = 0
    for item in items:
        try:
            if date_field in item and item[date_field] is not None:
                # Handle different date formats
                date_str = item[date_field]
                if isinstance(date_str, str) and date_str.strip():
                    item_date = parser.parse(date_str).date()
                    if start_date <= item_date <= end_date:
                        # Check state if filter is provided
                        if state_filter is None or item.get('state') == state_filter:
                            count += 1
        except (ValueError, TypeError, AttributeError) as e:
            # Skip items with invalid dates
            continue
    return count

# --- GATHER DATA FOR SINGLE USER ---
async def gather_user_data(username, start_date, end_date):
    async with aiohttp.ClientSession() as session:
        try:
            user = await fetch_json(
                session, f"{BASE_URL}/users", params={"username": username}
            )
            if not user:
                return None
            
            user = user[0]
            user_id = user["id"]
            user_email = user.get("public_email") or user.get("email", "")

            personal_projects = await fetch_user_projects(session, user_id)
            contributed_projects = await fetch_contributed_projects(session, user_id)

            contrib_data = {}
            for project in contributed_projects:
                project_id = project["id"]
                name = project["name_with_namespace"]
                contrib_data[name] = {"commits": [], "mrs": [], "issues": []}

                try:
                    commits = await fetch_commits(session, project_id, user_email)
                    contrib_data[name]["commits"] = commits or []
                except Exception as e:
                    contrib_data[name]["commits"] = []

                try:
                    mrs = await fetch_merge_requests(session, user_id, project_id)
                    if mrs:
                        for mr in mrs:
                            try:
                                comments = await fetch_mr_comments(
                                    session, project_id, mr["iid"]
                                )
                                mr["comment_count"] = len(comments) if comments else 0
                            except:
                                mr["comment_count"] = 0
                        contrib_data[name]["mrs"] = mrs
                    else:
                        contrib_data[name]["mrs"] = []
                except Exception as e:
                    contrib_data[name]["mrs"] = []

                try:
                    issues = await fetch_issues(session, user_id, project_id)
                    if issues:
                        for issue in issues:
                            try:
                                comments = await fetch_issue_comments(
                                    session, project_id, issue["iid"]
                                )
                                issue["comment_count"] = len(comments) if comments else 0
                            except:
                                issue["comment_count"] = 0
                        contrib_data[name]["issues"] = issues
                    else:
                        contrib_data[name]["issues"] = []
                except Exception as e:
                    contrib_data[name]["issues"] = []

            # Calculate totals with improved date filtering
            total_commits = sum(
                count_items_by_date(pdata.get("commits", []), "created_at", start_date, end_date)
                for pdata in contrib_data.values()
            )
            
            # Calculate MR statistics by state
            total_mrs_open = sum(
                count_items_by_date_and_state(pdata.get("mrs", []), "created_at", start_date, end_date, "opened")
                for pdata in contrib_data.values()
            )
            total_mrs_closed = sum(
                count_items_by_date_and_state(pdata.get("mrs", []), "created_at", start_date, end_date, "closed")
                for pdata in contrib_data.values()
            )
            total_mrs_merged = sum(
                count_items_by_date_and_state(pdata.get("mrs", []), "created_at", start_date, end_date, "merged")
                for pdata in contrib_data.values()
            )
            total_mrs = total_mrs_open + total_mrs_closed + total_mrs_merged
            
            # Calculate Issue statistics by state
            total_issues_open = sum(
                count_items_by_date_and_state(pdata.get("issues", []), "created_at", start_date, end_date, "opened")
                for pdata in contrib_data.values()
            )
            total_issues_closed = sum(
                count_items_by_date_and_state(pdata.get("issues", []), "created_at", start_date, end_date, "closed")
                for pdata in contrib_data.values()
            )
            total_issues = total_issues_open + total_issues_closed
            
            # Count comments within date range
            total_mr_comments = 0
            total_issue_comments = 0
            
            for pdata in contrib_data.values():
                # Count MR comments within date range
                for mr in pdata.get("mrs", []):
                    try:
                        mr_date = parser.parse(mr["created_at"]).date()
                        if start_date <= mr_date <= end_date:
                            total_mr_comments += mr.get("comment_count", 0)
                    except:
                        continue
                
                # Count issue comments within date range
                for issue in pdata.get("issues", []):
                    try:
                        issue_date = parser.parse(issue["created_at"]).date()
                        if start_date <= issue_date <= end_date:
                            total_issue_comments += issue.get("comment_count", 0)
                    except:
                        continue

            return {
                "username": user["username"],
                "name": user["name"],
                "commits": total_commits,
                "merge_requests": total_mrs,
                "mrs_open": total_mrs_open,
                "mrs_closed": total_mrs_closed,
                "mrs_merged": total_mrs_merged,
                "issues": total_issues,
                "issues_open": total_issues_open,
                "issues_closed": total_issues_closed,
                "mr_comments": total_mr_comments,
                "issue_comments": total_issue_comments,
                "total_contributions": total_commits + total_mrs + total_issues,
                "personal_projects": len(personal_projects),
                "contributed_projects": len(contributed_projects)
            }
            
        except Exception as e:
            st.error(f"Error fetching data for {username}: {str(e)}")
            return None

# --- GRADING FUNCTIONS ---
@st.cache_data
def calculate_grade(value, avg_value):
    if avg_value == 0:
        return "No Data"
    if value >= avg_value * 1.2:  # 20% above average
        return "Good"
    elif value >= avg_value * 0.8:  # Within 20% of average
        return "Average"
    else:  # Below 80% of average
        return "Below Average"

@st.cache_data
def add_grades_to_dataframe(df_dict):
    """Add grades to dataframe - accepts dict for caching"""
    df = pd.DataFrame(df_dict)
    df_graded = df.copy()
    
    # Calculate averages for grading metrics
    avg_commits = df['commits'].mean() if len(df) > 0 else 0
    avg_mrs = df['merge_requests'].mean() if len(df) > 0 else 0
    avg_contributions = df['total_contributions'].mean() if len(df) > 0 else 0
    
    # Add grade columns
    df_graded['commits_grade'] = df['commits'].apply(lambda x: calculate_grade(x, avg_commits))
    df_graded['mr_grade'] = df['merge_requests'].apply(lambda x: calculate_grade(x, avg_mrs))
    df_graded['contributions_grade'] = df['total_contributions'].apply(lambda x: calculate_grade(x, avg_contributions))
    
    return df_graded

# --- HELPER FUNCTIONS ---
def get_persistent_data():
    """Get the persistent fetched data"""
    return st.session_state.get(f"{STATE_PREFIX}fetched_data")

def set_persistent_data(data):
    """Set the persistent fetched data"""
    st.session_state[f"{STATE_PREFIX}fetched_data"] = data

def clear_persistent_data():
    """Clear all persistent data"""
    for key in list(st.session_state.keys()):
        if key.startswith(STATE_PREFIX):
            del st.session_state[key]
    init_persistent_state()

def clean_csv_data(df):
    """Clean CSV data to handle empty rows and mixed types"""
    # Remove completely empty rows
    df = df.dropna(how='all')
    
    # Remove rows where username is empty or NaN
    df = df.dropna(subset=['username'])
    
    # Convert username column to string and strip whitespace
    df['username'] = df['username'].astype(str).str.strip()
    
    # Remove any rows where username is empty string after stripping
    df = df[df['username'] != '']
    
    # Reset index
    df = df.reset_index(drop=True)
    
    return df

# --- STREAMLIT UI ---
st.title("📊 GitLab Student Progress Tracker")

# Add cache info
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.info("💡 Data is cached for better performance. Clear cache if you need fresh data.")
with col2:
    if st.button("🗑️ Clear Cache"):
        st.cache_data.clear()
        st.success("Cache cleared!")
        st.rerun()
with col3:
    if st.button("🔄 Reset All Data"):
        clear_persistent_data()
        st.cache_data.clear()
        st.success("All data reset!")
        st.rerun()

# Main upload section
st.subheader("📤 Upload Student Data CSV")

# Sample CSV format
with st.expander("📋 CSV Format Guide"):
    st.write("Your CSV should contain a column named 'username' with GitLab usernames:")
    sample_df = pd.DataFrame({
        'username': ['student1', 'student2', 'student3'],
        'name': ['John Doe', 'Jane Smith', 'Bob Johnson']
    })
    st.dataframe(sample_df)

uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

if uploaded_file is not None:
    try:
        # Read CSV with better error handling
        df_input = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
        
        if 'username' not in df_input.columns:
            st.error("CSV must contain a 'username' column")
        else:
            # Clean the CSV data
            df_input = clean_csv_data(df_input)
            
            if len(df_input) == 0:
                st.error("No valid usernames found in the CSV file")
            else:
                st.success(f"Loaded {len(df_input)} students from CSV")
                st.dataframe(df_input)
                
                # Date range selection
                st.subheader("📅 Select Date Range for Analysis")
                col_start, col_end = st.columns(2)
                start_date = col_start.date_input("Start Date", value=date(2020, 1, 1))
                end_date = col_end.date_input("End Date", value=date.today())
                
                # Check if we already have this data
                usernames = df_input['username'].tolist()
                current_hash = get_data_hash(usernames, start_date, end_date)
                cached_hash = st.session_state.get(f"{STATE_PREFIX}data_hash")
                
                if cached_hash == current_hash and get_persistent_data() is not None:
                    st.info("✅ Data already fetched for these parameters. Using cached results.")
                    st.write("Click 'Process Data' to view results or 'Force Refresh' to fetch new data.")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        process_cached = st.button("📊 Process Cached Data")
                    with col2:
                        force_refresh = st.button("🔄 Force Refresh Data")
                    
                    if process_cached:
                        st.session_state[f"{STATE_PREFIX}show_results"] = True
                        st.rerun()
                    elif force_refresh:
                        clear_persistent_data()
                        st.cache_data.clear()
                        st.rerun()
                
                if st.button("🚀 Fetch All Student Data") or st.session_state.get(f"{STATE_PREFIX}show_results", False):
                    if not st.session_state.get(f"{STATE_PREFIX}show_results", False):
                        # Fetch new data
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        all_data = []
                        total_students = len(df_input)
                        
                        for idx, row in df_input.iterrows():
                            username = row['username']
                            status_text.text(f"Fetching data for {username}... ({idx+1}/{total_students})")
                            
                            try:
                                user_data = gather_user_data_cached(
                                    username, 
                                    start_date.isoformat(), 
                                    end_date.isoformat()
                                )
                                if user_data:
                                    # Add any additional columns from original CSV
                                    for col in df_input.columns:
                                        if col != 'username' and col not in user_data:
                                            user_data[col] = row[col]
                                    all_data.append(user_data)
                                else:
                                    st.warning(f"No data found for user: {username}")
                            except Exception as e:
                                st.warning(f"Failed to fetch data for {username}: {str(e)}")
                            
                            progress_bar.progress((idx + 1) / total_students)
                        
                        if all_data:
                            df_results = add_grades_to_dataframe(all_data)
                            set_persistent_data(df_results)
                            st.session_state[f"{STATE_PREFIX}data_hash"] = current_hash
                            status_text.text("✅ Data fetching completed!")
                        else:
                            st.error("No data could be fetched for any student.")
                            st.stop()
                    
                    # Reset the show_results flag
                    if f"{STATE_PREFIX}show_results" in st.session_state:
                        del st.session_state[f"{STATE_PREFIX}show_results"]
        
    except Exception as e:
        st.error(f"Error reading CSV: {str(e)}")
        st.write("Please check your CSV file format and ensure it has proper structure.")

# Display results if data is available
fetched_data = get_persistent_data()
if fetched_data is not None:
    df = fetched_data
    
    st.subheader("📊 Student Progress Data")
    
    # Filter controls
    col1, col2, col3 = st.columns(3)
    
    with col1:
        metric_filter = st.selectbox(
            "Select Metric to Display",
            ["All Metrics", "Commits", "Merge Requests", "Issues", "Total Contributions"],
            key="metric_filter"
        )
    
    with col2:
        grade_filter = st.selectbox(
            "Filter by Grade",
            ["All Grades", "Good", "Average", "Below Average"],
            key="grade_filter"
        )
    
    with col3:
        if st.button("🔄 Reset Filters"):
            st.session_state.metric_filter = "All Metrics"
            st.session_state.grade_filter = "All Grades"
            st.rerun()
    
    # Apply filters
    df_filtered = df.copy()
    
    # Grade filtering
    if grade_filter != "All Grades":
        if metric_filter == "Commits":
            df_filtered = df_filtered[df_filtered['commits_grade'] == grade_filter]
        elif metric_filter == "Merge Requests":
            df_filtered = df_filtered[df_filtered['mr_grade'] == grade_filter]
        elif metric_filter == "Total Contributions":
            df_filtered = df_filtered[df_filtered['contributions_grade'] == grade_filter]
        else:
            # For "All Metrics", show students who have the selected grade in any metric
            mask = (
                (df_filtered['commits_grade'] == grade_filter) |
                (df_filtered['mr_grade'] == grade_filter) |
                (df_filtered['contributions_grade'] == grade_filter)
            )
            df_filtered = df_filtered[mask]
    
    # Column selection based on metric filter
    if metric_filter == "Commits":
        columns_to_show = ['username', 'name', 'commits', 'commits_grade']
    elif metric_filter == "Merge Requests":
        columns_to_show = ['username', 'name', 'merge_requests', 'mrs_open', 'mrs_closed', 'mrs_merged', 'mr_grade']
    elif metric_filter == "Issues":
        columns_to_show = ['username', 'name', 'issues', 'issues_open', 'issues_closed']
    elif metric_filter == "Total Contributions":
        columns_to_show = ['username', 'name', 'total_contributions', 'contributions_grade']
    else:  # All Metrics
        columns_to_show = [
            'username', 'name', 'commits', 'commits_grade',
            'merge_requests', 'mrs_open', 'mrs_closed', 'mrs_merged', 'mr_grade',
            'issues', 'issues_open', 'issues_closed', 'mr_comments',
            'issue_comments', 'total_contributions', 'contributions_grade',
            'personal_projects', 'contributed_projects'
        ]
    
    # Display filtered data
    df_display = df_filtered[columns_to_show]
    st.dataframe(df_display, use_container_width=True)
    
    # Summary statistics
    st.subheader("📈 Summary Statistics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Students", len(df_filtered))
    with col2:
        st.metric("Avg Commits", f"{df_filtered['commits'].mean():.1f}")
    with col3:
        st.metric("Avg Merge Requests", f"{df_filtered['merge_requests'].mean():.1f}")
    with col4:
        st.metric("Avg Issues", f"{df_filtered['issues'].mean():.1f}")
    
    # Additional statistics for MRs and Issues
    st.subheader("📊 Detailed Statistics")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Avg MRs Open", f"{df_filtered['mrs_open'].mean():.1f}")
    with col2:
        st.metric("Avg MRs Closed", f"{df_filtered['mrs_closed'].mean():.1f}")
    with col3:
        st.metric("Avg MRs Merged", f"{df_filtered['mrs_merged'].mean():.1f}")
    with col4:
        st.metric("Avg Issues Open", f"{df_filtered['issues_open'].mean():.1f}")
    with col5:
        st.metric("Avg Issues Closed", f"{df_filtered['issues_closed'].mean():.1f}")
    
    # Grade distribution
    if len(df_filtered) > 0:
        st.subheader("🎯 Grade Distribution")
        
        if metric_filter == "Commits":
            grade_counts = df_filtered['commits_grade'].value_counts()
        elif metric_filter == "Merge Requests":
            grade_counts = df_filtered['mr_grade'].value_counts()
        elif metric_filter == "Total Contributions":
            grade_counts = df_filtered['contributions_grade'].value_counts()
        else:
            # For all metrics, show combined distribution
            all_grades = pd.concat([
                df_filtered['commits_grade'],
                df_filtered['mr_grade'],
                df_filtered['contributions_grade']
            ])
            grade_counts = all_grades.value_counts()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Good", grade_counts.get("Good", 0))
        col2.metric("Average", grade_counts.get("Average", 0))
        col3.metric("Below Average", grade_counts.get("Below Average", 0))
    
    # Download CSV
    st.subheader("💾 Download Data")
    
    @st.cache_data
    def convert_df_to_csv(dataframe):
        return dataframe.to_csv(index=False).encode('utf-8')
    
    csv = convert_df_to_csv(df_display)
    
    st.download_button(
        label="📥 Download Filtered Data as CSV",
        data=csv,
        file_name=f'gitlab_student_progress_{metric_filter.lower().replace(" ", "_")}_{grade_filter.lower().replace(" ", "_")}.csv',
        mime='text/csv',
    )
    
    # Download full data
    csv_full = convert_df_to_csv(df)
    st.download_button(
        label="📥 Download Complete Data as CSV",
        data=csv_full,
        file_name='gitlab_student_progress_complete.csv',
        mime='text/csv',
    )
