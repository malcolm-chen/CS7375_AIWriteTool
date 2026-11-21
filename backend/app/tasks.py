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
    "client_apology": {
        "id": "client_apology",
        "title": "Apologize to a client after a costly mistake",
        "scenario": (
            "You're an account manager at a small marketing agency. For two years you've handled the account of a "
            "regional furniture retailer, working directly with its marketing director. Last Friday your agency "
            "launched the retailer's weekend sale ads with the wrong discount: 50% off instead of 15% off. You caught "
            "it Saturday morning and pulled the ads, but by then dozens of customers had come into the stores "
            "expecting half off, and some left angry. It happened because you approved the final proof without "
            "checking it against the client's brief."
        ),
        "assignment": (
            "Write an email, with a subject line, to the marketing director. They have already heard about the "
            "problem from their store managers and are upset. Your agency can't afford to lose this account."
        ),
        "minWords": 40,
        "placeholder": "Subject: \n\n",
    },
}

DEFAULT_TASK = "energy_job_inquiry"

# Every participant writes all of these, in an order randomized per participant (see assignment.py).
STUDY_TASKS = ["energy_job_inquiry", "client_apology"]

# Explanation conditions, one per task for each participant. Which task gets which condition is
# randomized and counterbalanced together with the task order.
#   reasons:   hovering an edit shows the AI's explanation.
#   noReasons: the explanation is withheld server-side; the participant sees a neutral question instead.
# The AI still writes explanations in both conditions; they are stored and exported, only not shown.
STUDY_CONDITIONS = ["reasons", "noReasons"]


def task_brief(task: dict) -> str:
    """Task text passed to the model, exactly as the participant saw it."""
    return f"{task['scenario']}\n\n{task['assignment']}"
