"""Predefined writing tasks shown to participants before the AI revision."""

TASKS: dict[str, dict] = {
    "energy_job_inquiry": {
        "id": "energy_job_inquiry",
        "title": "Email a company about a job after a layoff",
        "scenario": (
            "You've worked eight years at a Houston energy-trading company, most recently running its Texas "
            "electricity trading desk. You also have natural gas trading, purchasing, and pipeline experience. "
            "Three days ago your company went bankrupt and laid off thousands, and your job may be next."
        ),
        "assignment": (
            "Write an email, with a subject line, to the general hiring inbox of a large oil and gas company "
            "headquartered in The Woodlands, where you live. You don't know anyone there and haven't seen a job "
            "posting. Your resume is attached."
        ),
        "minWords": 40,
        "placeholder": "Subject: \n\n",
    },
}

DEFAULT_TASK = "energy_job_inquiry"


def task_brief(task: dict) -> str:
    """Task text passed to the model, exactly as the participant saw it."""
    return f"{task['scenario']}\n\n{task['assignment']}"
