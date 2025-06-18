
import streamlit as st
import asyncio
import aiohttp
from datetime import datetime, timedelta
from dateutil import parser
import pandas as pd
import re
import hashlib
import json

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]

# Cache TTL (Time To Live) in seconds - 1 hour
CACHE_TTL = 3600

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
if "mr_comments_data" not in st.session_state:
    st.session_state.mr_comments_data = None
if "issue_comments_data" not in st.session_state:
    st.session_state.issue_comments_data = None
if "last_username" not in st.session_state:
    st.session_state.last_username = ""
if "cache" not in st.session_state:
    st.session_state.cache = {}
if "cache_timestamps" not in st.session_state:
    st.session_state.cache_timestamps = {}

# --- CACHE FUNCTIONS ---
def get_cache_key(username, endpoint):
    """Generate a cache key for API responses"""
    return hashlib.md5(f"{username}_{endpoint}".encode()).hexdigest()

def is_cache_valid(cache_key):
    """Check if cached data is still valid"""
    if cache_key not in st.session_state.cache_timestamps:
        return False
    
    cache_time = st.session_state.cache_timestamps[cache_key]
    return (datetime.now() - cache_time).seconds < CACHE_TTL

def get_from_cache(cache_key):
    """Get data from cache if valid"""
    if is_cache_valid(cache_key):
        return st.session_state.cache.get(cache_key)
    return None

def save_to_cache(cache_key, data):
    """Save data to cache with timestamp"""
    st.session_state.cache[cache_key] = data
    st.session_state.cache_timestamps[cache_key] = datetime.now()

def clear_cache():
    """Clear all cached data"""
    st.session_state.cache = {}
    st.session_state.cache_timestamps = {}

def reset_all_data():
    """Reset all session state data"""
    st.session_state.user_data = None
    st.session_state.projects_data = None
    st.session_state.commits_data = None
    st.session_state.merge_requests_data = None
    st.session_state.issues_data = None
    st.session_state.mr_comments_data = None
    st.session_state.issue_comments_data = None
    st.session_state.last_username = ""
    clear_cache()

# --- API FETCH FUNCTIONS ---
@st.cache_data(ttl=CACHE_TTL)
def cached_fetch_json(url, params_str, headers_str):
    """Cached wrapper for API calls using Streamlit's cache"""
    import requests
    import json
    
    headers = json.loads(headers_str)
    params = json.loads(params_str) if params_str else None
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 401:
        raise Exception("❌ Unauthorized: Check your GitLab token or permissions.")
    response.raise_for_status()
    return response.json()

async def fetch_json(session, url, params=None):
    """Async API fetch with caching"""
    cache_key = get_cache_key(url, str(params))
    cached_data = get_from_cache(cache_key)
    
    if cached_data is not None:
        return cached_data
    
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    async with session.get(url, headers=headers, params=params) as response:
        if response.status == 401:
            raise Exception("❌ Unauthorized: Check your GitLab token or permissions.")
        response.raise_for_status()
        data = await response.json()
        
        # Save to cache
        save_to_cache(cache_key, data)
        return data

async def fetch_user(session, username):
    users = await fetch_json(
        session, f"{BASE_URL}/users", params={"username": username}
    )
    return users[0] if users else None

async def fetch_projects(session, user_id):
    try:
        return await fetch_json(session, f"{BASE_URL}/users/{user_id}/projects", params={"per_page": 100})
    except:
        return []

async def fetch_contributed_projects(session, user_id):
    try:
        return await fetch_json(
            session,
            f"{BASE_URL}/users/{user_id}/contributed_projects",
            params={"per_page": 100},
        )
    except:
        return []

async def fetch_all_accessible_projects(session):
    """Fetch all projects the token has access to"""
    try:
        return await fetch_json(session, f"{BASE_URL}/projects", params={"per_page": 100, "membership": "true"})
    except:
        return []

def is_commit_by_author(commit, username, user_email, user_name, user_id):
    """Enhanced check if commit is authored by the specific user"""
    author_name = commit.get("author_name", "").lower().strip()
    author_email = commit.get("author_email", "").lower().strip()
    committer_name = commit.get("committer_name", "").lower().strip()
    committer_email = commit.get("committer_email", "").lower().strip()
    
    username_lower = username.lower().strip()
    user_email_lower = user_email.lower().strip() if user_email else ""
    user_name_lower = user_name.lower().strip() if user_name else ""
    
    # Multiple ways to match the author
    name_matches = [
        author_name == username_lower,
        author_name == user_name_lower,
        committer_name == username_lower,
        committer_name == user_name_lower
    ]
    
    email_matches = [
        author_email == user_email_lower if user_email_lower else False,
        committer_email == user_email_lower if user_email_lower else False
    ]
    
    # Also check for partial name matches (common in different git configs)
    partial_matches = []
    if user_name_lower:
        name_parts = user_name_lower.split()
        if len(name_parts) >= 2:
            # Check if author name contains first and last name parts
            partial_matches.extend([
                all(part in author_name for part in name_parts[:2]),
                all(part in committer_name for part in name_parts[:2])
            ])
    
    return any(name_matches + email_matches + partial_matches)

async def fetch_commits_by_author(session, project_id, user_id, username, user_email, user_name, project_name):
    """Fetch commits by author with multiple strategies and caching"""
    cache_key = get_cache_key(f"commits_{project_id}_{user_id}", "")
    cached_commits = get_from_cache(cache_key)
    
    if cached_commits is not None:
        return cached_commits
    
    verified_commits = []
    
    try:
        # Strategy 1: Use author_id parameter
        try:
            commits = await fetch_json(
                session,
                f"{BASE_URL}/projects/{project_id}/repository/commits",
                params={"author_id": user_id, "per_page": 100, "all": "true"},
            )
            for commit in commits:
                if is_commit_by_author(commit, username, user_email, user_name, user_id):
                    commit['project_name'] = project_name
                    verified_commits.append(commit)
        except Exception as e:
            pass
        
        # Strategy 2: Use author email if available
        if user_email and not verified_commits:
            try:
                commits = await fetch_json(
                    session,
                    f"{BASE_URL}/projects/{project_id}/repository/commits",
                    params={"author": user_email, "per_page": 100, "all": "true"},
                )
                for commit in commits:
                    if is_commit_by_author(commit, username, user_email, user_name, user_id):
                        commit['project_name'] = project_name
                        verified_commits.append(commit)
            except Exception as e:
                pass
        
        # Strategy 3: Fetch all commits and filter (last resort)
        if not verified_commits:
            try:
                all_commits = await fetch_json(
                    session,
                    f"{BASE_URL}/projects/{project_id}/repository/commits",
                    params={"per_page": 50, "all": "true"},  # Reduced per_page for better performance
                )
                for commit in all_commits:
                    if is_commit_by_author(commit, username, user_email, user_name, user_id):
                        commit['project_name'] = project_name
                        verified_commits.append(commit)
            except Exception as e:
                pass
    
    except Exception as e:
        pass
    
    # Remove duplicates based on commit ID
    seen_ids = set()
    unique_commits = []
    for commit in verified_commits:
        if commit['id'] not in seen_ids:
            seen_ids.add(commit['id'])
            unique_commits.append(commit)
    
    # Cache the results
    save_to_cache(cache_key, unique_commits)
    return unique_commits

async def fetch_merge_requests(session, user_id):
    """Fetch merge requests authored by the user"""
    return await fetch_json(
        session,
        f"{BASE_URL}/merge_requests",
        params={"author_id": user_id, "scope": "all", "per_page": 100},
    )

async def fetch_issues(session, user_id):
    """Fetch issues created by the user"""
    return await fetch_json(
        session,
        f"{BASE_URL}/issues",
        params={"author_id": user_id, "scope": "all", "per_page": 100},
    )

async def fetch_all_mr_comments(session, user_id, projects):
    """Fetch ALL comments made by user on merge requests across all accessible projects"""
    cache_key = get_cache_key(f"mr_comments_{user_id}", "")
    cached_comments = get_from_cache(cache_key)
    
    if cached_comments is not None:
        return cached_comments
    
    all_comments = []
    
    # Limit to first 20 projects for performance
    limited_projects = projects[:20] if len(projects) > 20 else projects
    
    for project in limited_projects:
        try:
            project_id = project["id"]
            project_name = project.get("name_with_namespace", project.get("name", "Unknown"))
            
            # Get recent merge requests in this project (limit for performance)
            merge_requests = await fetch_json(
                session,
                f"{BASE_URL}/projects/{project_id}/merge_requests",
                params={"state": "all", "per_page": 50, "order_by": "updated_at"}
            )
            
            for mr in merge_requests:
                try:
                    mr_iid = mr["iid"]
                    
                    # Get MR notes/comments
                    notes = await fetch_json(
                        session,
                        f"{BASE_URL}/projects/{project_id}/merge_requests/{mr_iid}/notes",
                        params={"per_page": 50}
                    )
                    
                    # Filter comments by the specific user
                    user_notes = [note for note in notes if note.get("author", {}).get("id") == user_id]
                    for note in user_notes:
                        note["mr_title"] = mr["title"]
                        note["mr_url"] = mr.get("web_url", "")
                        note["project_name"] = project_name
                    all_comments.extend(user_notes)
                except Exception as e:
                    continue
        except Exception as e:
            continue
    
    # Cache the results
    save_to_cache(cache_key, all_comments)
    return all_comments

async def fetch_all_issue_comments(session, user_id, projects):
    """Fetch ALL comments made by user on issues across all accessible projects"""
    cache_key = get_cache_key(f"issue_comments_{user_id}", "")
    cached_comments = get_from_cache(cache_key)
    
    if cached_comments is not None:
        return cached_comments
    
    all_comments = []
    
    # Limit to first 20 projects for performance
    limited_projects = projects[:20] if len(projects) > 20 else projects
    
    for project in limited_projects:
        try:
            project_id = project["id"]
            project_name = project.get("name_with_namespace", project.get("name", "Unknown"))
            
            # Get recent issues in this project (limit for performance)
            issues = await fetch_json(
                session,
                f"{BASE_URL}/projects/{project_id}/issues",
                params={"state": "all", "per_page": 50, "order_by": "updated_at"}
            )
            
            for issue in issues:
                try:
                    issue_iid = issue["iid"]
                    
                    # Get issue notes/comments
                    notes = await fetch_json(
                        session,
                        f"{BASE_URL}/projects/{project_id}/issues/{issue_iid}/notes",
                        params={"per_page": 50}
                    )
                    
                    # Filter comments by the specific user
                    user_notes = [note for note in notes if note.get("author", {}).get("id") == user_id]
                    for note in user_notes:
                        note["issue_title"] = issue["title"]
                        note["issue_url"] = issue.get("web_url", "")
                        note["project_name"] = project_name
                    all_comments.extend(user_notes)
                except Exception as e:
                    continue
        except Exception as e:
            continue
    
    # Cache the results
    save_to_cache(cache_key, all_comments)
    return all_comments

# --- MAIN GATHER FUNCTION ---
async def gather_data(username):
    async with aiohttp.ClientSession() as session:
        user = await fetch_user(session, username)
        if not user:
            raise ValueError("User not found!")
        
        user_id = user["id"]
        user_email = user.get("public_email") or user.get("email", "")
        user_name = user.get("name", "")
        
        st.info(f"🔍 Found user: {user_name} (ID: {user_id})")
        st.info(f"📧 Email: {user_email or 'Not available'}")
        
        # Fetch projects - get both owned and contributed, plus all accessible
        owned_projects = await fetch_projects(session, user_id)
        contributed_projects = await fetch_contributed_projects(session, user_id)
        all_accessible_projects = await fetch_all_accessible_projects(session)
        
        # Combine all projects and deduplicate
        all_projects = {}
        for proj in owned_projects + contributed_projects + all_accessible_projects:
            all_projects[proj["id"]] = proj
        projects = list(all_projects.values())
        
        # Limit projects for better performance
        if len(projects) > 50:
            st.warning(f"⚠️ Found {len(projects)} projects. Limiting to first 50 for performance.")
            projects = projects[:50]
        
        st.info(f"📁 Scanning {len(projects)} total projects ({len(owned_projects)} owned, {len(contributed_projects)} contributed)")
        
        # Fetch commits for each project with progress tracking
        commits_by_project = {}
        total_commits = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, project in enumerate(projects):
            project_id = project["id"]
            project_name = project.get("name_with_namespace", project.get("name", "Unknown"))
            
            status_text.text(f"Processing: {project_name[:50]}...")
            
            commits = await fetch_commits_by_author(
                session, project_id, user_id, username, user_email, user_name, project_name
            )
            
            if commits:
                commits_by_project[project_name] = commits
                total_commits += len(commits)
            
            progress_bar.progress((i + 1) / len(projects))
        
        status_text.empty()
        st.success(f"📝 Found {total_commits} total commits across {len(commits_by_project)} projects")
        
        # Fetch MRs and Issues authored by user
        merge_requests = await fetch_merge_requests(session, user_id)
        issues = await fetch_issues(session, user_id)
        
        st.info(f"🔀 Found {len(merge_requests)} merge requests authored by user")
        st.info(f"🐛 Found {len(issues)} issues created by user")
        
        # Fetch ALL comments made by user across all projects
        st.info("💬 Fetching comments across projects...")
        mr_comments = await fetch_all_mr_comments(session, user_id, projects)
        issue_comments = await fetch_all_issue_comments(session, user_id, projects)
        
        st.success(f"💬 Found {len(mr_comments)} MR comments, {len(issue_comments)} issue comments")
        
        return user, projects, commits_by_project, merge_requests, issues, mr_comments, issue_comments

def calculate_contribution_stats(commits_by_project, merge_requests, issues, mr_comments, issue_comments):
    """Calculate comprehensive contribution statistics"""
    total_commits = sum(len(commits) for commits in commits_by_project.values())
    total_mrs = len(merge_requests)
    total_issues = len(issues)
    total_mr_comments = len(mr_comments)
    total_issue_comments = len(issue_comments)
    total_contributions = total_commits + total_mrs + total_issues + total_mr_comments + total_issue_comments
    
    return {
        "total_commits": total_commits,
        "total_mrs": total_mrs,
        "total_issues": total_issues,
        "total_mr_comments": total_mr_comments,
        "total_issue_comments": total_issue_comments,
        "total_contributions": total_contributions
    }

def format_commit_message(message):
    """Format commit message to show type and scope"""
    # Common commit prefixes
    patterns = {
        r'^feat(\(.+\))?:': '🆕 Feature',
        r'^fix(\(.+\))?:': '🐛 Fix',
        r'^docs(\(.+\))?:': '📚 Docs',
        r'^style(\(.+\))?:': '💄 Style',
        r'^refactor(\(.+\))?:': '♻️ Refactor',
        r'^test(\(.+\))?:': '🧪 Test',
        r'^chore(\(.+\))?:': '🔧 Chore',
        r'^perf(\(.+\))?:': '⚡ Performance',
        r'^ci(\(.+\))?:': '👷 CI',
        r'^build(\(.+\))?:': '📦 Build',
    }
    
    for pattern, emoji_type in patterns.items():
        if re.match(pattern, message, re.IGNORECASE):
            return f"{emoji_type} | {message}"
    
    return f"📝 Commit | {message}"

def create_clickable_link(url, text):
    """Create a clickable link using HTML"""
    if url and url != "#":
        return f'<a href="{url}" target="_blank">{text}</a>'
    return text

def display_dataframe_with_links(df, link_columns):
    """Display dataframe with clickable links"""
    # Convert link columns to HTML
    df_display = df.copy()
    for col in link_columns:
        if col in df_display.columns:
            # Extract URLs and create clickable links
            df_display[col] = df_display[col].apply(
                lambda x: x if not isinstance(x, str) or not x.startswith('[') else 
                create_clickable_link(
                    x.split('(')[1].split(')')[0] if '(' in x and ')' in x else '#',
                    x.split(']')[0][1:] if ']' in x else 'View'
                )
            )
    
    # Display with HTML rendering
    st.write(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="GitLab Contribution Dashboard", page_icon="📊", layout="wide")

st.title("📊 GitLab Contribution Dashboard")
st.markdown("**Comprehensive tracking of commits, issues, MRs, and comments by a specific author across all accessible projects**")

# Add control buttons in the top area
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.markdown("---")
with col2:
    if st.button("🔄 Clear Cache", help="Clear cached data to fetch fresh information"):
        clear_cache()
        st.success("✅ Cache cleared!")
        st.rerun()
with col3:
    if st.button("🗑️ Reset All", help="Reset all data and start fresh"):
        reset_all_data()
        st.success("✅ All data reset!")
        st.rerun()

username = st.text_input("🔍 Enter GitLab Username", value=st.session_state.last_username, placeholder="e.g., john.doe")

# Show cache status
if st.session_state.cache:
    cache_info = f"💾 Cache: {len(st.session_state.cache)} items stored"
    oldest_cache = min(st.session_state.cache_timestamps.values()) if st.session_state.cache_timestamps else datetime.now()
    cache_age = (datetime.now() - oldest_cache).seconds // 60
    if cache_age < 60:
        cache_info += f" (oldest: {cache_age}m ago)"
    else:
        cache_info += f" (oldest: {cache_age//60}h {cache_age%60}m ago)"
    st.caption(cache_info)

need_fetch = username and (
    username != st.session_state.last_username or st.session_state.user_data is None
)

if username and need_fetch:
    with st.spinner("🔄 Fetching comprehensive GitLab data (this may take a while)..."):
        try:
            user, projects, commits_by_project, merge_requests, issues, mr_comments, issue_comments = asyncio.run(
                gather_data(username)
            )
            st.session_state.user_data = user
            st.session_state.projects_data = projects
            st.session_state.commits_data = commits_by_project
            st.session_state.merge_requests_data = merge_requests
            st.session_state.issues_data = issues
            st.session_state.mr_comments_data = mr_comments
            st.session_state.issue_comments_data = issue_comments
            st.session_state.last_username = username
            st.success("✅ Data fetched successfully!")
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.error("Please check your GitLab token, permissions, and base URL.")

if username and st.session_state.user_data:
    user = st.session_state.user_data
    projects = st.session_state.projects_data
    commits_by_project = st.session_state.commits_data
    merge_requests = st.session_state.merge_requests_data
    issues = st.session_state.issues_data
    mr_comments = st.session_state.mr_comments_data
    issue_comments = st.session_state.issue_comments_data
    
    # Calculate stats
    stats = calculate_contribution_stats(commits_by_project, merge_requests, issues, mr_comments, issue_comments)
    
    # User Profile Section
    col1, col2 = st.columns([1, 2])
    with col1:
        if user.get('avatar_url'):
            st.image(user.get('avatar_url', ''), width=150)
    with col2:
        st.subheader(f"👤 {user['name']} (@{user['username']})")
        st.write(f"📧 **Email:** {user.get('public_email', 'Not public')}")
        
        # Handle member since date safely
        try:
            if user.get('created_at'):
                member_since = parser.parse(user['created_at']).strftime('%B %Y')
                st.write(f"📅 **Member since:** {member_since}")
        except:
            pass
            
        if user.get('bio'):
            st.write(f"📝 **Bio:** {user['bio']}")
        
        # Add profile link
        if user.get('web_url'):
            st.markdown(f"🔗 **Profile:** [{user['web_url']}]({user['web_url']})")
    
    st.markdown("---")
    
    # Statistics Overview
    st.subheader("📈 Contribution Statistics")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.metric("📝 Total Commits", stats["total_commits"])
    with col2:
        st.metric("🔀 Merge Requests", stats["total_mrs"])
    with col3:
        st.metric("🐛 Issues Created", stats["total_issues"])
    with col4:
        st.metric("💬 MR Comments", stats["total_mr_comments"])
    with col5:
        st.metric("💭 Issue Comments", stats["total_issue_comments"])
    with col6:
        st.metric("🎯 Total Contributions", stats["total_contributions"])
    
    st.markdown("---")
    
    # Filters
    st.subheader("🔧 Filters")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        show_commits = st.checkbox("📝 Show Commits", value=True)
        show_mrs = st.checkbox("🔀 Show Merge Requests", value=True)
    with col2:
        show_issues = st.checkbox("🐛 Show Issues", value=True)
        show_comments = st.checkbox("💬 Show Comments", value=True)
    with col3:
        project_names = list(commits_by_project.keys()) if commits_by_project else []
        selected_project = st.selectbox("📁 Filter by Project", ["All Projects"] + project_names)
    
    # Date range filter
    min_date, max_date = datetime(2020, 1, 1), datetime.now()
    date_range = st.date_input("📅 Filter by Date Range", [min_date.date(), max_date.date()])
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range[0] if date_range else min_date.date()
    
    st.markdown("---")
    
    # Commits Section
    if show_commits and commits_by_project:
        st.subheader("📝 Commits by Author")
        
        for project_name, commits in commits_by_project.items():
            if selected_project != "All Projects" and project_name != selected_project:
                continue
            if not commits:
                continue
            
            # Filter by date
            filtered = []
            for commit in commits:
                try:
                    if commit.get("created_at"):
                        commit_date = parser.parse(commit["created_at"]).date()
                        if start_date <= commit_date <= end_date:
                            filtered.append(commit)
                except Exception as e:
                    continue
            
            if not filtered:
                continue
            
            with st.expander(f"📁 {project_name} ({len(filtered)} commits)", expanded=len(commits_by_project) <= 3):
                data = []
                for i, c in enumerate(filtered, start=1):
                    try:
                        commit_date = parser.parse(c["created_at"]).strftime("%Y-%m-%d %H:%M") if c.get("created_at") else "Unknown"
                        commit_link = c.get("web_url", "#")
                        formatted_message = format_commit_message(c.get("title", "No message"))
                        
                        data.append({
                            "#": i,
                            "Type & Message": formatted_message[:80] + "..." if len(formatted_message) > 80 else formatted_message,
                            "Author": c.get("author_name", "Unknown"),
                            "Author Email": c.get("author_email", "Unknown"),
                            "Date": commit_date,
                            "SHA": c.get("short_id", c.get("id", "")[:8]),
                            "Link": commit_link if commit_link != "#" else "No link"
                        })
                    except Exception as e:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    # Create clickable links
                    df['Link'] = df['Link'].apply(lambda x: f'<a href="{x}" target="_blank">🔗 View</a>' if x != "No link" else "No link")
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
    
    # Merge Requests Section
    if show_mrs and merge_requests:
        st.subheader("🔀 Merge Requests by Author")
        
        # Filter MRs by date
        filtered_mrs = []
        for mr in merge_requests:
            try:
                if mr.get("created_at"):
                    mr_date = parser.parse(mr["created_at"]).date()
                    if start_date <= mr_date <= end_date:
                        filtered_mrs.append(mr)
            except Exception as e:
                continue
        
        if filtered_mrs:
            data = []
            for i, mr in enumerate(filtered_mrs, start=1):
                try:
                    mr_date = parser.parse(mr["created_at"]).strftime("%Y-%m-%d %H:%M") if mr.get("created_at") else "Unknown"
                    state_emoji = "✅" if mr.get("state") == "merged" else "🔄" if mr.get("state") == "opened" else "❌"
                    
                    data.append({
                        "#": i,
                        "Title": mr.get("title", "No title")[:60] + "..." if len(mr.get("title", "")) > 60 else mr.get("title", "No title"),
                        "State": f"{state_emoji} {mr.get('state', 'unknown').title()}",
                        "Project": mr.get("references", {}).get("full", "Unknown"),
                        "Created": mr_date,
                        "Updated": parser.parse(mr["updated_at"]).strftime("%Y-%m-%d %H:%M") if mr.get("updated_at") else "Unknown",
                        "Target Branch": mr.get("target_branch", "Unknown"),
                        "Source Branch": mr.get("source_branch", "Unknown"),
                        "Link": mr.get("web_url", "#")
                    })
                except Exception as e:
                    continue
            
            if data:
                df = pd.DataFrame(data)
                # Create clickable links
                df['Link'] = df['Link'].apply(lambda x: f'<a href="{x}" target="_blank">🔗 View MR</a>' if x != "#" else "No link")
                st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.info("No merge requests found in the selected date range.")
    
    # Issues Section
    if show_issues and issues:
        st.subheader("🐛 Issues Created by Author")
        
        # Filter issues by date
        filtered_issues = []
        for issue in issues:
            try:
                if issue.get("created_at"):
                    issue_date = parser.parse(issue["created_at"]).date()
                    if start_date <= issue_date <= end_date:
                        filtered_issues.append(issue)
            except Exception as e:
                continue
        
        if filtered_issues:
            data = []
            for i, issue in enumerate(filtered_issues, start=1):
                try:
                    issue_date = parser.parse(issue["created_at"]).strftime("%Y-%m-%d %H:%M") if issue.get("created_at") else "Unknown"
                    state_emoji = "✅" if issue.get("state") == "closed" else "🔓"
                    
                    # Get labels
                    labels = ", ".join(issue.get("labels", [])) if issue.get("labels") else "None"
                    
                    data.append({
                        "#": i,
                        "Title": issue.get("title", "No title")[:60] + "..." if len(issue.get("title", "")) > 60 else issue.get("title", "No title"),
                        "State": f"{state_emoji} {issue.get('state', 'unknown').title()}",
                        "Project": issue.get("references", {}).get("full", "Unknown"),
                        "Labels": labels[:30] + "..." if len(labels) > 30 else labels,
                        "Created": issue_date,
                        "Updated": parser.parse(issue["updated_at"]).strftime("%Y-%m-%d %H:%M") if issue.get("updated_at") else "Unknown",
                        "Link": issue.get("web_url", "#")
                    })
                except Exception as e:
                    continue
            
            if data:
                df = pd.DataFrame(data)
                # Create clickable links
                df['Link'] = df['Link'].apply(lambda x: f'<a href="{x}" target="_blank">🔗 View Issue</a>' if x != "#" else "No link")
                st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.info("No issues found in the selected date range.")
    
    # Comments Section
    if show_comments and (mr_comments or issue_comments):
        st.subheader("💬 Comments by Author")
        
        # MR Comments
        if mr_comments:
            st.markdown("#### 🔀 Merge Request Comments")
            
            # Filter MR comments by date
            filtered_mr_comments = []
            for comment in mr_comments:
                try:
                    if comment.get("created_at"):
                        comment_date = parser.parse(comment["created_at"]).date()
                        if start_date <= comment_date <= end_date:
                            filtered_mr_comments.append(comment)
                except Exception as e:
                    continue
            
            if filtered_mr_comments:
                data = []
                for i, comment in enumerate(filtered_mr_comments, start=1):
                    try:
                        comment_date = parser.parse(comment["created_at"]).strftime("%Y-%m-%d %H:%M") if comment.get("created_at") else "Unknown"
                        body_preview = comment.get("body", "")[:100] + "..." if len(comment.get("body", "")) > 100 else comment.get("body", "")
                        
                        data.append({
                            "#": i,
                            "MR Title": comment.get("mr_title", "Unknown")[:50] + "..." if len(comment.get("mr_title", "")) > 50 else comment.get("mr_title", "Unknown"),
                            "Project": comment.get("project_name", "Unknown")[:40] + "..." if len(comment.get("project_name", "")) > 40 else comment.get("project_name", "Unknown"),
                            "Comment Preview": body_preview,
                            "Created": comment_date,
                            "Updated": parser.parse(comment["updated_at"]).strftime("%Y-%m-%d %H:%M") if comment.get("updated_at") else "Unknown",
                            "Link": comment.get("mr_url", "#")
                        })
                    except Exception as e:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    # Create clickable links
                    df['Link'] = df['Link'].apply(lambda x: f'<a href="{x}" target="_blank">🔗 View MR</a>' if x != "#" else "No link")
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No MR comments found in the selected date range.")
        
        # Issue Comments
        if issue_comments:
            st.markdown("#### 🐛 Issue Comments")
            
            # Filter issue comments by date
            filtered_issue_comments = []
            for comment in issue_comments:
                try:
                    if comment.get("created_at"):
                        comment_date = parser.parse(comment["created_at"]).date()
                        if start_date <= comment_date <= end_date:
                            filtered_issue_comments.append(comment)
                except Exception as e:
                    continue
            
            if filtered_issue_comments:
                data = []
                for i, comment in enumerate(filtered_issue_comments, start=1):
                    try:
                        comment_date = parser.parse(comment["created_at"]).strftime("%Y-%m-%d %H:%M") if comment.get("created_at") else "Unknown"
                        body_preview = comment.get("body", "")[:100] + "..." if len(comment.get("body", "")) > 100 else comment.get("body", "")
                        
                        data.append({
                            "#": i,
                            "Issue Title": comment.get("issue_title", "Unknown")[:50] + "..." if len(comment.get("issue_title", "")) > 50 else comment.get("issue_title", "Unknown"),
                            "Project": comment.get("project_name", "Unknown")[:40] + "..." if len(comment.get("project_name", "")) > 40 else comment.get("project_name", "Unknown"),
                            "Comment Preview": body_preview,
                            "Created": comment_date,
                            "Updated": parser.parse(comment["updated_at"]).strftime("%Y-%m-%d %H:%M") if comment.get("updated_at") else "Unknown",
                            "Link": comment.get("issue_url", "#")
                        })
                    except Exception as e:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    # Create clickable links
                    df['Link'] = df['Link'].apply(lambda x: f'<a href="{x}" target="_blank">🔗 View Issue</a>' if x != "#" else "No link")
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.info("No issue comments found in the selected date range.")
    
    # Activity Timeline
    st.markdown("---")
    st.subheader("📅 Activity Timeline")
    
    # Combine all activities with dates
    all_activities = []
    
    # Add commits
    if commits_by_project:
        for project_name, commits in commits_by_project.items():
            for commit in commits:
                if commit.get("created_at"):
                    try:
                        date = parser.parse(commit["created_at"])
                        if start_date <= date.date() <= end_date:
                            all_activities.append({
                                "date": date,
                                "type": "📝 Commit",
                                "title": commit.get("title", "No title")[:50] + "..." if len(commit.get("title", "")) > 50 else commit.get("title", "No title"),
                                "project": project_name,
                                "url": commit.get("web_url", "#")
                            })
                    except Exception as e:
                        continue
    
    # Add merge requests
    if merge_requests:
        for mr in merge_requests:
            if mr.get("created_at"):
                try:
                    date = parser.parse(mr["created_at"])
                    if start_date <= date.date() <= end_date:
                        all_activities.append({
                            "date": date,
                            "type": "🔀 Merge Request",
                            "title": mr.get("title", "No title")[:50] + "..." if len(mr.get("title", "")) > 50 else mr.get("title", "No title"),
                            "project": mr.get("references", {}).get("full", "Unknown"),
                            "url": mr.get("web_url", "#")
                        })
                except Exception as e:
                    continue
    
    # Add issues
    if issues:
        for issue in issues:
            if issue.get("created_at"):
                try:
                    date = parser.parse(issue["created_at"])
                    if start_date <= date.date() <= end_date:
                        all_activities.append({
                            "date": date,
                            "type": "🐛 Issue",
                            "title": issue.get("title", "No title")[:50] + "..." if len(issue.get("title", "")) > 50 else issue.get("title", "No title"),
                            "project": issue.get("references", {}).get("full", "Unknown"),
                            "url": issue.get("web_url", "#")
                        })
                except Exception as e:
                    continue
    
    # Add comments
    if mr_comments:
        for comment in mr_comments:
            if comment.get("created_at"):
                try:
                    date = parser.parse(comment["created_at"])
                    if start_date <= date.date() <= end_date:
                        all_activities.append({
                            "date": date,
                            "type": "💬 MR Comment",
                            "title": f"Comment on: {comment.get('mr_title', 'Unknown MR')}"[:50] + "..." if len(f"Comment on: {comment.get('mr_title', 'Unknown MR')}") > 50 else f"Comment on: {comment.get('mr_title', 'Unknown MR')}",
                            "project": comment.get("project_name", "Unknown"),
                            "url": comment.get("mr_url", "#")
                        })
                except Exception as e:
                    continue
    
    if issue_comments:
        for comment in issue_comments:
            if comment.get("created_at"):
                try:
                    date = parser.parse(comment["created_at"])
                    if start_date <= date.date() <= end_date:
                        all_activities.append({
                            "date": date,
                            "type": "💭 Issue Comment",
                            "title": f"Comment on: {comment.get('issue_title', 'Unknown Issue')}"[:50] + "..." if len(f"Comment on: {comment.get('issue_title', 'Unknown Issue')}") > 50 else f"Comment on: {comment.get('issue_title', 'Unknown Issue')}",
                            "project": comment.get("project_name", "Unknown"),
                            "url": comment.get("issue_url", "#")
                        })
                except Exception as e:
                    continue
    
    # Sort by date (most recent first)
    all_activities.sort(key=lambda x: x["date"], reverse=True)
    
    if all_activities:
        # Limit to recent activities for performance
        recent_activities = all_activities[:100]  # Show last 100 activities
        
        data = []
        for i, activity in enumerate(recent_activities, start=1):
            data.append({
                "#": i,
                "Date": activity["date"].strftime("%Y-%m-%d %H:%M"),
                "Type": activity["type"],
                "Title": activity["title"],
                "Project": activity["project"][:40] + "..." if len(activity["project"]) > 40 else activity["project"],
                "Link": activity["url"]
            })
        
        df = pd.DataFrame(data)
        # Create clickable links
        df['Link'] = df['Link'].apply(lambda x: f'<a href="{x}" target="_blank">🔗 View</a>' if x != "#" else "No link")
        
        st.caption(f"Showing {len(recent_activities)} most recent activities (out of {len(all_activities)} total)")
        st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("No activities found in the selected date range.")

# Footer
st.markdown("---")
st.markdown("**GitLab Contribution Dashboard** | Built with ❤️ using Streamlit")
st.caption("💡 Tip: Use the filters above to narrow down your results. Data is cached for better performance.")