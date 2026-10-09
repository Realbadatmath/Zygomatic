<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# CrewAI Timeline Schedule Scripts

This directory contains organized scripts for managing and visualizing CrewAI agent schedules across different time periods.

## Scripts Overview

### 1. `24_hour_timeline.py`
**Purpose**: Manages and visualizes 24-hour timeline data
**Features**:
- Generates 24-hour timeline visualization based on PNG structure
- Manages schedule entries for a single day
- Validates schedule entries
- Provides timeline data for web interface
- Supports the exact model-to-agent mapping from the PNG visualization

**Key Methods**:
- `get_todays_entries(date)` - Get all entries for a specific date
- `add_schedule_entry(entry, date)` - Add new schedule entry
- `generate_timeline_visualization(date, output_file)` - Generate PNG visualization
- `validate_schedule_entry(entry)` - Validate entry data

### 2. `7_day_timeline.py`
**Purpose**: Manages and visualizes 7-day timeline data
**Features**:
- Weekly schedule overview
- Daily entry counts and GPU usage
- Model usage summary over 7 days
- Multiple visualization types

**Key Methods**:
- `get_week_entries(start_date)` - Get entries for 7-day period
- `get_daily_summary(start_date)` - Daily breakdown
- `generate_week_visualization(start_date, output_file)` - Generate weekly charts
- `get_model_usage_summary(start_date)` - Model usage over week

### 3. `28_day_timeline.py`
**Purpose**: Manages and visualizes 28-day timeline data (4 weeks)
**Features**:
- Monthly schedule overview
- Weekly and daily breakdowns
- Calendar-style visualization
- Comprehensive model usage tracking

**Key Methods**:
- `get_month_entries(start_date)` - Get entries for 28-day period
- `get_weekly_summary(start_date)` - Weekly breakdown
- `generate_month_visualization(start_date, output_file)` - Generate monthly charts
- `generate_calendar_view(start_date, output_file)` - Calendar-style view

### 4. `1_year_timeline.py`
**Purpose**: Manages and visualizes 1-year timeline data
**Features**:
- Annual schedule overview
- Monthly and quarterly breakdowns
- Activity heatmap
- Historical trend analysis

**Key Methods**:
- `get_year_entries(start_date)` - Get entries for 1-year period
- `get_monthly_summary(start_date)` - Monthly breakdown
- `generate_year_visualization(start_date, output_file)` - Generate annual charts
- `generate_quarterly_report(start_date, output_file)` - Quarterly analysis

### 5. `history_timeline.py`
**Purpose**: Manages and visualizes historical schedule data
**Features**:
- Comprehensive historical analysis
- Date range summaries
- Model usage over time
- Text summary reports

**Key Methods**:
- `get_all_historical_entries()` - Get all past entries
- `get_historical_summary()` - Historical data summary
- `generate_historical_visualization(output_file)` - Historical charts
- `generate_summary_report(output_file)` - Text report

### 6. `add_entry_timeline.py`
**Purpose**: Manages adding, editing, and validating schedule entries
**Features**:
- Entry validation and conflict checking
- CRUD operations for schedule entries
- Available time slot detection
- Form data management

**Key Methods**:
- `add_schedule_entry(entry, date)` - Add new entry
- `edit_schedule_entry(entry_id, updated_entry, date)` - Edit existing entry
- `delete_schedule_entry(entry_id, date)` - Delete entry
- `validate_schedule_entry(entry)` - Validate entry data
- `check_schedule_conflicts(entry)` - Check for conflicts

### 7. `timeline_orchestrator.py`
**Purpose**: Main controller that manages all timeline functionality
**Features**:
- Unified interface for all timeline operations
- Data export/import functionality
- Comprehensive summaries
- Batch visualization generation

**Key Methods**:
- `get_timeline_data(timeline_type, **kwargs)` - Get data for any timeline
- `generate_visualization(timeline_type, **kwargs)` - Generate visualizations
- `add_schedule_entry(entry, date)` - Add entries
- `export_schedule_data(output_file)` - Export data
- `import_schedule_data(import_file)` - Import data

## AI Model Mapping

All scripts use the same AI model to agent count mapping based on the PNG visualization:

```python
model_agent_mapping = {
    'Stable Diffusion 1.5 XL': 4,
    'Dreambooth_Stable_Diffusion': 4,
    'FastAPI': 4,
    'Claude_3': 3,
    'RealESRGAN': 3,
    'Blender_(bpy)': 3,
    'Whisper': 3,
    'Stable Video Diffusion': 2,
    'Bark': 2,
    'Bark-Voice-Cloning': 2,
    'Mistral': 1,
    'LLaMA-3': 1,
    'CrewAi': 1,
    'HumanEval': 1,
    'DreamShaper_RealisticVision': 1,
    'ControlNet': 1,
    'AnimateDiff': 1,
    'Davinci_Resolve': 1,
    'Tortoise_TTS': 1,
    'AI_QC_Engine': 1,
    'CLIP': 1,
    'LoRA': 1,
    'Plotly': 1,
    'Airflow': 1,
    'autosave_daemon': 1,
}
```

## Usage Examples

### Basic Usage

```python
# Initialize orchestrator
orchestrator = TimelineOrchestrator()

# Get 24-hour timeline data
data_24h = orchestrator.get_timeline_data('24h')

# Generate visualization
orchestrator.generate_visualization('24h', output_file='my_timeline.png')

# Add a schedule entry
entry = {
    'ai_model': 'Claude_3',
    'start_time': '09:00',
    'end_time': '17:00',
    'gpu_percent': '99.9',
    'memory_fraction': '0.10',
    'gpu_device': 'NVIDIA GeForce GTX 970',
    'priority': 'High',
    'agent': 'CEO_Agent',
}
result = orchestrator.add_schedule_entry(entry)
```

### Individual Script Usage

```python
# 24-hour timeline
from timeline_24h import Timeline24Hour

timeline_24h = Timeline24Hour()
timeline_24h.generate_timeline_visualization()

# 7-day timeline
from timeline_7d import Timeline7Day

timeline_7d = Timeline7Day()
timeline_7d.generate_week_visualization()

# Add entry
from add_entry_timeline import AddEntryTimeline

add_entry = AddEntryTimeline()
success, message = add_entry.add_schedule_entry(entry)
```

## Data Structure

Schedule entries follow this structure:

```json
{
  "ai_model": "Claude_3",
  "start_time": "09:00",
  "end_time": "17:00",
  "gpu_percent": "99.9",
  "memory_fraction": "0.10",
  "gpu_device": "NVIDIA GeForce GTX 970",
  "priority": "High",
  "agent": "CEO_Agent",
  "date": "2025-01-07",
  "id": "uuid-string"
}
```

## Dependencies

Required Python packages:
- `matplotlib` - For visualizations
- `numpy` - For numerical operations
- `datetime` - For date/time handling
- `json` - For data serialization
- `uuid` - For unique ID generation

## File Organization

```
Schedule/
├── 24_hour_timeline.py      # 24-hour timeline management
├── 7_day_timeline.py        # 7-day timeline management
├── 28_day_timeline.py       # 28-day timeline management
├── 1_year_timeline.py       # 1-year timeline management
├── history_timeline.py      # Historical data management
├── add_entry_timeline.py    # Entry management
├── timeline_orchestrator.py # Main orchestrator
├── README.md               # This documentation
├── schedule_data.json      # Schedule data file
└── timeline_24h.png         # Reference PNG
```

## Integration with Web Interface

These scripts are designed to integrate with the existing CrewAI web interface. The orchestrator provides a unified API that can be called from the web application to:

1. Get timeline data for different periods
2. Generate visualizations
3. Manage schedule entries
4. Export/import data

## Testing

Each script includes a `main()` function for testing. Run individual scripts to test their functionality:

```bash
python 24_hour_timeline.py
python 7_day_timeline.py
python timeline_orchestrator.py
```

## Future Enhancements

Potential improvements:
- Real-time schedule updates
- Conflict resolution algorithms
- Advanced visualization options
- Integration with external calendar systems
- Automated schedule optimization
- Multi-user support with permissions 