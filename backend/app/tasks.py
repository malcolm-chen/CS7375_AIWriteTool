"""Predefined writing tasks shown to participants before the AI revision."""

TASKS: dict[str, dict] = {
    "salary_negotiation": {
        "id": "salary_negotiation",
        "title": "Negotiate your first job offer",
        "scenario": (
            "You're finishing your degree and just got your first full-time offer: a role at a company you'd love to "
            "work for. The base salary is $95,000. From what you've seen on salary sites and heard from friends, "
            "similar roles pay about $105,000. The recruiter, Jordan, has been friendly and asked you to reply by "
            "Friday. You're also in the final round of interviews at another company, but you don't have an offer "
            "from them. You really want this job and don't want to seem ungrateful or risk the offer."
        ),
        "assignment": (
            "Write an email to Jordan, with a subject line, responding to the offer and asking for a higher salary."
        ),
        "minWords": 40,
        "placeholder": "Subject: \n\n",
    },
    "professor_apology": {
        "id": "professor_apology",
        "title": "Apologize to a professor who vouched for you",
        "scenario": (
            "You're a master's student. Professor Morgan, whose class you did well in, offered to introduce you to "
            "Dr. Patel, a senior researcher at the company where you most want a summer internship. Professor Morgan "
            "set up a 30-minute video call for last Tuesday at 10 a.m. You missed it: you had the time down for "
            "10 a.m. in the wrong time zone and realized an hour later. Dr. Patel waited 15 minutes, then emailed "
            "Professor Morgan to ask whether you were still interested. Professor Morgan forwarded you that email "
            "this morning with one line: \"What happened?\""
        ),
        "assignment": "Write an email to Professor Morgan, with a subject line.",
        "minWords": 40,
        "placeholder": "Subject: \n\n",
    },
}

# Every participant writes all of these, in an order randomized per participant (see assignment.py).
STUDY_TASKS = ["salary_negotiation", "professor_apology"]

# Explanation conditions, one per task for each participant. Which task gets which condition is
# randomized and counterbalanced together with the task order.
#   reasons:   hovering an edit shows the AI's explanation.
#   noReasons: the explanation is withheld server-side; the participant sees a neutral question instead.
# The AI still writes explanations in both conditions; they are stored and exported, only not shown.
STUDY_CONDITIONS = ["reasons", "noReasons"]


def task_brief(task: dict) -> str:
    """Task text passed to the model, exactly as the participant saw it."""
    return f"{task['scenario']}\n\n{task['assignment']}"
