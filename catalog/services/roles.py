from django.utils.translation import gettext_lazy as _

ROLE_LABELS = {
    "producer": _("Producer"),
    "mix": _("Mix"),
    "engineer": _("Engineering"),
    "recording engineer": _("Recording engineering"),
    "mastering": _("Mastering"),
    "audio": _("Audio"),
    "recorded at": _("Recorded at"),
    "instrument": _("Instruments"),
    "vocal": _("Vocals"),
    "arranger": _("Arrangements"),
    "conductor": _("Conducting"),
}


def role_label(role: str):
    return ROLE_LABELS.get(role.lower()) or role.capitalize()
