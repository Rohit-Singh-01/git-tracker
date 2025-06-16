# GitLab Personal + Contribution Tracker

A comprehensive Streamlit application that tracks and analyzes GitLab user contributions, designed for educational institutions to monitor student progress and individual developers to track their coding activity.

## 🚀 Features

### Individual Tracking (`app.py`)
- **Personal Dashboard**: Track individual GitLab user contributions
- **Real-time Data Fetching**: Async API calls for efficient data retrieval
- **Contribution Metrics**: Commits, merge requests, issues, and comments
- **Date Range Filtering**: Analyze contributions within specific time periods
- **Project Overview**: View personal and contributed projects
- **Session Persistence**: Data persists during the session

### Bulk Summary Tracker (`bulk_summary.py`)

- Track multiple GitLab users' contributions at once using CSV or manual input.  
- Get detailed metrics on commits, merge requests, issues, and comments.  
- Includes caching, error handling, and real-time status updates per user.  
- Responsive and memory-efficient with time-based analytics and breakdowns.

### Individual Detailed View (`detailed_view.py`)

- Visualize a single user’s GitLab activity with rich, real-time analytics.  
- Explore commits, merge requests, and issues interactively with filters.  
- Includes PDF export, charts grouped by time, and session-based caching.  
- User-friendly UI with smart error handling and responsive design.

### Bulk Student Progress Tracking (`progress_view.py`)
- **CSV Upload**: Bulk upload student usernames via CSV file
- **Grading System**: Automatic grade assignment (Good/Average/Below Average)
- **Performance Comparison**: Compare students against class averages
- **Data Caching**: Intelligent caching for improved performance
- **Export Functionality**: Download results as CSV files
- **Filter & Sort**: Multiple filtering options for data analysis

## 📊 Metrics Tracked

### Core Contribution Metrics
- **Commits**: Total commits authored by the user
- **Merge Requests**: MRs created by the user
- **Issues**: Issues opened by the user
- **MR Comments**: Comments on merge requests
- **Issue Comments**: Comments on issues
- **Total Contributions**: Sum of commits, MRs, and issues

### Project Metrics
- **Personal Projects**: Projects owned by the user
- **Contributed Projects**: Projects the user has contributed to

## 🔧 Technical Architecture

### API Integration
The application integrates with GitLab's REST API v4 using the following endpoints:

#### User Information
```
GET /api/v4/users?username={username}
```
Retrieves user profile information including ID, name, and email.

#### Project Data
```
GET /api/v4/users/{user_id}/projects
GET /api/v4/users/{user_id}/contributed_projects?per_page=100
```
Fetches personal and contributed projects for the user.

#### Contribution Data
```
GET /api/v4/projects/{project_id}/repository/commits?author_email={email}
GET /api/v4/projects/{project_id}/merge_requests?author_id={user_id}
GET /api/v4/projects/{project_id}/issues?author_id={user_id}&state=all
```
Retrieves commits, merge requests, and issues created by the user.

#### Comments and Notes
```
GET /api/v4/projects/{project_id}/issues/{issue_iid}/notes
GET /api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes
```
Fetches comments and discussions on issues and merge requests.

### Authentication
The application uses GitLab Personal Access Tokens for authentication:
```python
headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
```

### Async Processing
Utilizes `aiohttp` for concurrent API requests to improve performance:
```python
async def fetch_json(session, url, params=None):
    async with session.get(url, headers=headers, params=params) as response:
        response.raise_for_status()
        return await response.json()
```

## 🛠️ Setup & Installation

### Prerequisites
- Python 3.8+
- GitLab instance access
- GitLab Personal Access Token

### Dependencies
```
streamlit>=1.20
aiohttp>=3.8
pandas>=1.5
numpy>=1.21
python-dateutil>=2.8
fpdf2>=2.5
altair>=4.2
```

### Configuration
Create a `.streamlit/secrets.toml` file:
```toml
[gitlab]
token = "your_gitlab_personal_access_token"
base_url = "https://your-gitlab-instance.com/api/v4"
```

### Installation
```bash
# Clone the repository
git clone <repository-url>
cd gitlab-tracker

# Install dependencies
pip install -r requirements.txt

# Run the application
streamlit run app.py
# or for progress tracking
streamlit run progress_view.py
```

## 📝 Usage

### Individual Tracking
1. Launch `app.py`
2. Enter a GitLab username
3. Select date range for analysis
4. View detailed contribution metrics
5. Explore project-specific breakdowns

### Student Progress Tracking
1. Launch `progress_view.py`
2. Prepare CSV file with student usernames
3. Upload CSV file
4. Select analysis date range
5. Fetch student data (with progress indicator)
6. View graded results and comparisons
7. Export filtered data as needed

### CSV Format
Your CSV file should contain at minimum:
```csv
username,name
student1,John Doe
student2,Jane Smith
student3,Bob Johnson
```

## 🎯 Grading System

The application automatically assigns grades based on performance relative to class averages:

- **Good**: 20% or more above class average
- **Average**: Within 20% of class average (±20%)
- **Below Average**: More than 20% below class average

Grades are calculated for:
- Commit count
- Merge request count
- Total contributions

## 🔄 Caching & Performance

### Intelligent Caching
- User data cached for 30 minutes
- Full dataset cached for 1 hour
- CSV processing cached based on content hash
- Session state persistence across page interactions

### Performance Optimizations
- Async API calls for concurrent data fetching
- Progress indicators for long-running operations
- Efficient date filtering algorithms
- Memory-conscious data structures

## 📤 Export Features

### Available Export Formats
- **Filtered CSV**: Export currently filtered view
- **Complete CSV**: Export all fetched data
- **Custom filename**: Automatic naming based on filters

### Export Data Includes
- Student identification (username, name)
- All contribution metrics
- Grade assignments
- Project counts
- Comment statistics

## 🔐 Security Considerations

- **Token Security**: GitLab tokens stored in Streamlit secrets
- **API Rate Limiting**: Built-in error handling for API limits
- **Data Privacy**: No persistent storage of student data
- **Session Isolation**: Each session maintains separate data

## 🐛 Error Handling

The application includes comprehensive error handling:
- **API Failures**: Network timeout and HTTP error handling
- **Invalid Users**: Graceful handling of non-existent usernames
- **Date Parsing**: Robust date format handling
- **Missing Data**: Safe handling of incomplete API responses

## 📈 Use Cases

### Educational Institutions
- Monitor student engagement in GitLab projects
- Identify students needing additional support
- Generate progress reports for academic assessment
- Compare class performance over time



