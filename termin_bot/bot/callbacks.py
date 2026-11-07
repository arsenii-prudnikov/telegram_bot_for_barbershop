"""Callback-Daten der Inline-Buttons (max. 64 Byte pro Button)."""

from aiogram.filters.callback_data import CallbackData


class Menu(CallbackData, prefix="m"):
    action: str  # book | my | services | contact | lang | home


class Lang(CallbackData, prefix="l"):
    code: str


class Svc(CallbackData, prefix="s"):
    sid: str


class Mst(CallbackData, prefix="p"):
    sid: str
    mid: str  # "any" = egal


class Day(CallbackData, prefix="d"):
    sid: str
    mid: str
    day: str  # JJJJMMTT
    r: int = 0  # ID des Termins, der verschoben wird (0 = Neubuchung)


class Days(CallbackData, prefix="ds"):
    sid: str
    mid: str
    page: int
    r: int = 0


class Tm(CallbackData, prefix="t"):
    sid: str
    mid: str
    day: str
    hm: str  # HHMM
    r: int = 0


class Ok(CallbackData, prefix="ok"):
    sid: str
    mid: str
    day: str
    hm: str
    r: int = 0


class Wait(CallbackData, prefix="w"):
    sid: str
    day: str


class App(CallbackData, prefix="a"):
    aid: int
    action: str  # cancel | cancel_yes | move


class Rate(CallbackData, prefix="r"):
    aid: int
    stars: int


class Adm(CallbackData, prefix="x"):
    action: str  # today | tomorrow | week | stats | noshow | cancel | day
    arg: str = ""
