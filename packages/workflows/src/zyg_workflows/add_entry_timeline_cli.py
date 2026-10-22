# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.add_entry_timeline`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.add_entry_timeline` still reaches it.
"""

from zyg_workflows.add_entry_timeline import AddEntryTimeline


def main():
    """Main function for testing"""
    add_entry = AddEntryTimeline()

    # Test creating a sample entry
    sample_entry = add_entry.create_sample_entry('Claude_3')
    print('Sample entry:', sample_entry)

    # Test validation
    is_valid, message = add_entry.validate_schedule_entry(sample_entry)
    print(f'Validation: {is_valid}, Message: {message}')

    # Test adding entry
    success, message = add_entry.add_schedule_entry(sample_entry)
    print(f'Add entry: {success}, Message: {message}')

    # Get form data
    form_data = add_entry.get_entry_form_data()
    print(f'Available models: {len(form_data["available_models"])}')
    print(f"Today's entries: {len(form_data['todays_entries'])}")

    # Test available time slots
    available_slots = add_entry.get_available_time_slots('Claude_3')
    print(f'Available time slots for Claude_3: {available_slots}')


if __name__ == '__main__':
    main()
