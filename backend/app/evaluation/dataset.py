"""A small, fully synthetic evaluation set: eight documents and labelled questions.

Everything here is invented, so the set can live in the repository and anyone can re-run the
evaluation. Each question names the *fact* that answers it (``marker``, a short phrase that
occurs in exactly one place of the corpus), not a chunk id. A retrieved chunk is relevant
when it contains the marker, which keeps the labels valid whatever chunk size is tested.

The questions are grouped by what they stress:

* ``paraphrase`` - the question shares (almost) no words with the answer. This is where
  embeddings help and word matching fails.
* ``exact`` - the question is a code, a part number or a name. This is where word matching
  helps and embeddings are weak.
* ``natural`` - an ordinary question that uses the document's own vocabulary.
* ``confusable`` - another document says something similar, so the retriever must pick the
  right one (e.g. "90 days" appears in the password and the log-retention rules).
"""

from dataclasses import dataclass
from typing import Literal

Category = Literal["paraphrase", "exact", "natural", "confusable"]


@dataclass(frozen=True)
class EvalDocument:
    filename: str
    pages: tuple[str, ...]  # one string per page; a plain-text file has a single "page"


@dataclass(frozen=True)
class EvalQuestion:
    text: str
    marker: str  # lower-case phrase that appears in every relevant chunk
    category: Category


_CORE_DOCUMENTS: tuple[EvalDocument, ...] = (
    EvalDocument(
        "it_security_policy.txt",
        (
            "IT Security Policy\n\n"
            "Passwords must be changed every 90 days. A new password may not repeat any of "
            "your last twelve passwords, and it must be at least fourteen characters long. "
            "Never share a password with a colleague, not even with the IT helpdesk.\n\n"
            "Multi-factor authentication is mandatory for email, the VPN and the finance "
            "system. If you lose the phone that holds your authenticator app, open a ticket "
            "in the helpdesk portal and a technician will reset your factor after checking "
            "your identity in person.\n\n"
            "Lost or stolen devices: if a laptop or phone that belongs to the company is "
            "lost or stolen, report it within 4 hours to the security desk so that the "
            "device can be locked and wiped remotely. Do not wait until the next working "
            "day, even if the device was probably only left at home.\n\n"
            "Removable storage: USB sticks and external drives are prohibited on company "
            "laptops. Use the approved file-sharing service to move files between machines.",
        ),
    ),
    EvalDocument(
        "travel_and_expenses.txt",
        (
            "Travel and Expenses\n\n"
            "Flights and trains are booked through the travel portal, never directly with "
            "the airline. Economy class applies to every flight shorter than six hours.\n\n"
            "Hotels may cost at most 180 per night in a city and 130 per night elsewhere. "
            "The per diem for meals is 65 per day of travel. A receipt is required for every "
            "single purchase above 25.\n\n"
            "Using a private car for business is reimbursed at 0.58 per mile. Parking and "
            "tolls are paid back in full when the receipt is attached.\n\n"
            "Submit the expense report within 30 days of the end of the trip. Reports "
            "handed in later are paid with the following month's salary at the earliest.",
        ),
    ),
    EvalDocument(
        "leave_policy.txt",
        (
            "Leave Policy\n\n"
            "Every employee receives 25 days of paid annual leave per calendar year. Up to "
            "5 unused days may be carried over into the next year; the rest expire on the "
            "last day of March.\n\n"
            "Sick leave: ten paid sick days are available per year without a doctor's note "
            "for absences of up to two consecutive days. Longer absences need a medical "
            "certificate.\n\n"
            "New parents, regardless of gender, are entitled to 16 weeks of paid parental "
            "leave. The leave can be taken in one block or split into two blocks within the "
            "first year after the birth or adoption.\n\n"
            "After seven years of service an employee may apply for a paid sabbatical of "
            "four weeks, subject to approval by the department head.",
        ),
    ),
    EvalDocument(
        "pump_manual.pdf",
        (
            "Model P-300 Circulation Pump: Troubleshooting\n\n"
            "Error code E-4471 means the pump has lost pressure. Check the inlet valve and "
            "the seal before restarting the pump. Error code E-2209 means the motor "
            "overheated; switch the pump off and wait twenty minutes.",
            "Maintenance\n\n"
            "Service the pump every 500 operating hours. Replace the filter cartridge FC-88 "
            "at every service and tighten the housing bolts to 45 Nm. Use only the grease "
            "supplied in service kit SK-12.\n\n"
            "Storage: drain the pump completely before storing it below freezing "
            "temperatures, otherwise the housing may crack.",
        ),
    ),
    EvalDocument(
        "onboarding_guide.txt",
        (
            "Onboarding Guide\n\n"
            "On your first day, collect your access badge from the reception desk between "
            "nine and ten o'clock. Your laptop is prepared by IT and handed over during the "
            "welcome session.\n\n"
            "Every newcomer gets a buddy, an experienced colleague who answers practical "
            "questions during the first three months. Meet your buddy for lunch in the first "
            "week.\n\n"
            "Your manager agrees a 30-60-90 day plan with you during the first week. The "
            "plan lists learning goals for the first month, the second month and the third "
            "month. Mandatory security and compliance courses are in the training portal "
            "and must be completed within 14 days.",
        ),
    ),
    EvalDocument(
        "incident_response.txt",
        (
            "Incident Response Runbook\n\n"
            "A SEV1 incident means customers cannot use the product at all. The on-call "
            "engineer must acknowledge a SEV1 alert within 15 minutes and open the incident "
            "channel. SEV2 incidents degrade a feature and are acknowledged within one hour.\n\n"
            "The on-call duty rotates weekly and changes hands on Monday at ten o'clock. "
            "The outgoing engineer writes a short handover note.\n\n"
            "During an incident the status page is updated every 30 minutes, even when "
            "there is nothing new to report. After the incident, a blameless postmortem "
            "is published within 5 business days.",
        ),
    ),
    EvalDocument(
        "facilities.txt",
        (
            "Office and Facilities\n\n"
            "The cafeteria serves lunch between noon and two o'clock and is closed at "
            "weekends. Coffee is free on every floor.\n\n"
            "Parking permits are issued by the facilities team and are valid for one year. "
            "Bicycles can be stored in the locked cellar; ask reception for the door code.\n\n"
            "Meeting rooms are booked in the calendar tool and released automatically if "
            "nobody checks in within ten minutes. Visitors must be registered at reception "
            "the day before and always wear a visitor badge.",
        ),
    ),
    EvalDocument(
        "data_retention.txt",
        (
            "Data Retention Policy\n\n"
            "Application logs are kept for 90 days and then deleted automatically. Logs "
            "must never contain passwords or payment card numbers.\n\n"
            "Customer records are retained for seven years after the end of the contract "
            "because of tax law. Afterwards they are anonymised.\n\n"
            "All backups are encrypted with AES-256 and stored in a second region. A "
            "restore test is performed every quarter.\n\n"
            "A customer who asks for deletion of their personal data must receive an answer "
            "within 30 days. The data protection officer confirms the deletion in writing.",
        ),
    ),
)


_CORE_QUESTIONS: tuple[EvalQuestion, ...] = (
    # --- paraphrase: no shared vocabulary with the answer -----------------------------------
    EvalQuestion("How often do I need to pick a new login secret?", "every 90 days", "paraphrase"),
    EvalQuestion("What should I do if my work computer is stolen?", "within 4 hours", "paraphrase"),
    EvalQuestion(
        "What is the most I can spend on a place to sleep in a big city?",
        "180 per night",
        "paraphrase",
    ),
    EvalQuestion(
        "How long can new mums and dads stay home with a newborn?", "16 weeks", "paraphrase"
    ),
    EvalQuestion(
        "How soon after a trip must I ask to be paid back?",
        "within 30 days of the end of the trip",
        "paraphrase",
    ),
    EvalQuestion(
        "Who gets assigned to help me settle in during my first months?",
        "gets a buddy",
        "paraphrase",
    ),
    EvalQuestion(
        "What do I do when my pump suddenly stops building up force?", "lost pressure", "paraphrase"
    ),
    EvalQuestion(
        "What happens if the engine of the pump gets too hot?", "motor overheated", "paraphrase"
    ),
    EvalQuestion(
        "When can I get a long break after many years at the company?",
        "after seven years of service",
        "paraphrase",
    ),
    EvalQuestion(
        "How quickly must the engineer on duty react when the whole product is down?",
        "within 15 minutes",
        "paraphrase",
    ),
    # --- exact: codes, part numbers, names ---------------------------------------------------
    EvalQuestion("E-4471", "e-4471", "exact"),
    EvalQuestion("What does error E-2209 mean?", "e-2209", "exact"),
    EvalQuestion("Which cartridge is FC-88?", "fc-88", "exact"),
    EvalQuestion("What is SK-12?", "sk-12", "exact"),
    EvalQuestion("What does a SEV1 incident mean?", "a sev1 incident", "exact"),
    EvalQuestion("AES-256", "aes-256", "exact"),
    EvalQuestion("0.58 per mile", "0.58 per mile", "exact"),
    EvalQuestion("30-60-90 plan", "30-60-90 day plan", "exact"),
    # --- natural: the document's own words ---------------------------------------------------
    EvalQuestion(
        "How many days of annual leave do I get?", "25 days of paid annual leave", "natural"
    ),
    EvalQuestion("How many unused leave days can be carried over?", "5 unused days", "natural"),
    EvalQuestion("What is the meal per diem?", "per diem for meals is 65", "natural"),
    EvalQuestion(
        "What is the torque for the housing bolts?", "tighten the housing bolts to 45 nm", "natural"
    ),
    EvalQuestion("How often must the pump be serviced?", "every 500 operating hours", "natural"),
    EvalQuestion("When is lunch served in the cafeteria?", "between noon and two", "natural"),
    EvalQuestion(
        "How long must the status page be updated during an incident?",
        "updated every 30 minutes",
        "natural",
    ),
    EvalQuestion(
        "Are USB sticks allowed on company laptops?", "usb sticks and external drives", "natural"
    ),
    EvalQuestion("How long are application logs kept?", "logs are kept for 90 days", "natural"),
    # --- confusable: a similar sentence exists elsewhere -------------------------------------
    EvalQuestion(
        "How long until a postmortem is published?", "within 5 business days", "confusable"
    ),
    EvalQuestion(
        "How long do I have to complete the mandatory courses?", "within 14 days", "confusable"
    ),
    EvalQuestion(
        "How long do we keep customer records after a contract ends?",
        "seven years after the end of the contract",
        "confusable",
    ),
    EvalQuestion(
        "How long may a deletion request take to answer?",
        "within 30 days. the data protection officer",
        "confusable",
    ),
    EvalQuestion(
        "How many days a year can I be sick without a doctor's note?",
        "ten paid sick days",
        "confusable",
    ),
)


# --- ten near-identical office guides ------------------------------------------------------
# The same three sentences with different numbers for every city. A question names the city;
# the retriever has to tell nearly identical passages apart. This is the hard part of the set:
# embeddings place all ten canteen sentences almost on top of each other.

_OFFICES: tuple[tuple[str, str, int, int], ...] = (
    # city, canteen closing time, monthly parking permit, visitor notice in hours
    ("Lisbon", "17:30", 42, 24),
    ("Oslo", "16:45", 95, 48),
    ("Prague", "18:15", 38, 12),
    ("Dublin", "17:00", 110, 36),
    ("Vienna", "16:30", 72, 24),
    ("Warsaw", "18:00", 29, 6),
    ("Madrid", "19:00", 55, 18),
    ("Zurich", "15:45", 140, 72),
    ("Athens", "17:45", 33, 8),
    ("Helsinki", "16:15", 88, 30),
)


def _office_guide(city: str, close: str, permit: int, notice: int) -> EvalDocument:
    return EvalDocument(
        f"office_guide_{city.lower()}.txt",
        (
            f"{city} Office Guide\n\n"
            f"The {city} canteen opens at 08:00 and closes at {close}. Hot meals are "
            f"served until one hour before closing.\n\n"
            f"A monthly parking permit for the {city} office costs {permit} euros. "
            f"Permits are collected at the {city} front desk.\n\n"
            f"Visitors to the {city} office must be announced {notice} hours in advance "
            f"and collect a visitor badge at the {city} front desk.",
        ),
    )


_OFFICE_DOCUMENTS = tuple(_office_guide(*office) for office in _OFFICES)

_OFFICE_QUESTIONS: tuple[EvalQuestion, ...] = tuple(
    [
        EvalQuestion(
            f"When does the canteen in {city} close?",
            f"the {city.lower()} canteen opens at 08:00 and closes at {close}",
            "confusable",
        )
        for city, close, _, _ in _OFFICES[:4]
    ]
    + [
        EvalQuestion(
            f"How much is a monthly parking permit in {city}?",
            f"parking permit for the {city.lower()} office costs {permit} euros",
            "confusable",
        )
        for city, _, permit, _ in _OFFICES[4:8]
    ]
    + [
        EvalQuestion(
            f"How far in advance must a visitor be announced in {city}?",
            f"visitors to the {city.lower()} office must be announced {notice} hours",
            "confusable",
        )
        for city, _, _, notice in _OFFICES[8:] + _OFFICES[:2]
    ]
)

DOCUMENTS: tuple[EvalDocument, ...] = _CORE_DOCUMENTS + _OFFICE_DOCUMENTS
QUESTIONS: tuple[EvalQuestion, ...] = _CORE_QUESTIONS + _OFFICE_QUESTIONS
