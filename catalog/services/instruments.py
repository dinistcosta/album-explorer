from django.utils.translation import gettext_lazy as _

INSTRUMENT_LABELS = {
    "vocals": _("vocals"),
    "lead vocals": _("lead vocals"),
    "backing vocals": _("backing vocals"),
    "background vocals": _("background vocals"),
    "guitar": _("guitar"),
    "electric guitar": _("electric guitar"),
    "acoustic guitar": _("acoustic guitar"),
    "bass guitar": _("bass guitar"),
    "bass": _("bass"),
    "drums": _("drums"),
    "drums (drum set)": _("drums (drum set)"),
    "percussion": _("percussion"),
    "keyboard": _("keyboard"),
    "piano": _("piano"),
    "synthesizer": _("synthesizer"),
    "organ": _("organ"),
    "saxophone": _("saxophone"),
    "trumpet": _("trumpet"),
    "violin": _("violin"),
    "cello": _("cello"),
    "harmonica": _("harmonica"),
}


def instrument_label(name: str):
    return INSTRUMENT_LABELS.get(name.lower()) or name
