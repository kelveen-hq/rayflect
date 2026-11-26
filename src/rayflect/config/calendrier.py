"""Le calendrier et l'heure des horaires humains.

Ce module rend, pour chaque heure de la météo, l'heure et la date des horaires humains, le jour de la semaine et
si le jour est ouvré pour le profil d'occupation de l'usage. La météo et le soleil restent en temps universel :
seuls les horaires humains (occupation, réduit, éclairage, ventilation programmée, aération des occupants)
passent à l'heure légale.

LES RÉGLAGES (arguments de `calendrier_horaire`). La première valeur est le défaut ; la seconde est l'ancien
comportement, conservé pour compatibilité :
  - `horaires_base` : « locale » (heure légale du fuseau) ou « utc » (l'heure universelle de la météo sert
    d'heure des horaires humains) ;
  - `calendrier_jours_semaine` : « reels » (le vrai calendrier de l'année) ou « jour0_lundi » (le premier jour
    de la série est un lundi, quelle que soit l'année) ;
  - `calendrier_scolaire` : « zone_a » (vacances scolaires de la zone A) ou « aucun » (pas de vacances) ;
  - `calendrier_commerce` : « lundi_samedi » (samedi ouvré) ou « lundi_vendredi » ;
  - `calendrier_jours_feries` : « feries » (jours fériés fermés) ou « aucun ».

LES SOURCES.
  - Vacances scolaires, zone A (académie de Bordeaux depuis la rentrée 2015) : jeu ouvert du ministère de
    l'Éducation nationale « Le calendrier scolaire » (data.education.gouv.fr, `fr-en-calendrier-scolaire`,
    lieu « Bordeaux », population « Élèves »), pour les années 2017-2018 à 2025-2026. Les
    années 2015-2016 et 2016-2017 n'y figurent pas pour la zone A : elles sont transcrites des arrêtés fixant
    le calendrier scolaire (Bulletin officiel), dates à revérifier. Hors de la table, une RÈGLE TYPE (voir
    `_vacances_regle_type`), dite comme telle. Le confinement du printemps 2020 n'est PAS modélisé : c'est un
    calendrier type d'exploitation, pas l'histoire d'une année.
  - Jours fériés : code du travail, art. L3133-1 (11 jours : 1er janvier, lundi de Pâques, 1er et 8 mai,
    Ascension, lundi de Pentecôte, 14 juillet, 15 août, 1er et 11 novembre, 25 décembre). Bureaux, école et
    industrie fermés ces jours-là ; le commerce, ouvert d'ordinaire les jours fériés, ferme le 1er mai (seul
    jour chômé obligatoire, art. L3133-4), le 25 décembre et le 1er janvier (HYPOTHÈSE d'usage).
  - Commerce du lundi au samedi : repos dominical (code du travail, art. L3132-3), samedi ouvré.
  - Heure légale : base IANA (`zoneinfo`, paquet `tzdata`), heure d'été comprise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

HORAIRES_BASES = ("locale", "utc")
JOURS_SEMAINE = ("reels", "jour0_lundi")
CALENDRIERS_SCOLAIRES = ("zone_a", "aucun")
CALENDRIERS_COMMERCE = ("lundi_samedi", "lundi_vendredi")
JOURS_FERIES = ("feries", "aucun")

FUSEAU_DEFAUT = "Europe/Paris"
# Le fuseau du pays de la requête (`country_code`).
FUSEAU_PAR_PAYS: Dict[str, str] = {
    "FR": "Europe/Paris", "ES": "Europe/Madrid", "IT": "Europe/Rome", "DE": "Europe/Berlin",
    "PT": "Europe/Lisbon", "GR": "Europe/Athens", "BE": "Europe/Brussels", "CH": "Europe/Zurich",
    "LU": "Europe/Luxembourg", "NL": "Europe/Amsterdam", "GB": "Europe/London", "UK": "Europe/London",
}

# Vacances scolaires de la zone A : (premier jour sans classe, jour de la reprise), la reprise exclue. Jeu ouvert
# du ministère : `start_date` et `end_date` relus en heure de Paris (le jeu les publie en temps universel, la
# veille à 22 h ou 23 h). « Pont de l'Ascension » compris quand le jeu le publie.
_VACANCES_ZONE_A: Dict[str, Tuple[Tuple[str, str], ...]] = {
    # Arrêtés (BO), absents du jeu ouvert pour la zone A : à revérifier.
    "2015-2016": (("2015-10-17", "2015-11-02"), ("2015-12-19", "2016-01-04"), ("2016-02-13", "2016-02-29"),
                  ("2016-04-09", "2016-04-25"), ("2016-07-05", "2016-09-01")),
    "2016-2017": (("2016-10-20", "2016-11-03"), ("2016-12-17", "2017-01-03"), ("2017-02-11", "2017-02-27"),
                  ("2017-04-08", "2017-04-24"), ("2017-07-08", "2017-09-04")),
    # Jeu ouvert data.education.gouv.fr, lieu « Bordeaux », élèves.
    "2017-2018": (("2017-10-21", "2017-11-06"), ("2017-12-23", "2018-01-08"), ("2018-02-10", "2018-02-26"),
                  ("2018-04-07", "2018-04-23"), ("2018-07-07", "2018-09-03")),
    "2018-2019": (("2018-10-20", "2018-11-05"), ("2018-12-22", "2019-01-07"), ("2019-02-16", "2019-03-04"),
                  ("2019-04-13", "2019-04-29"), ("2019-05-29", "2019-06-03"), ("2019-07-06", "2019-09-02")),
    "2019-2020": (("2019-10-19", "2019-11-04"), ("2019-12-21", "2020-01-06"), ("2020-02-22", "2020-03-09"),
                  ("2020-04-18", "2020-05-04"), ("2020-05-20", "2020-05-25"), ("2020-07-04", "2020-09-01")),
    "2020-2021": (("2020-10-17", "2020-11-02"), ("2020-12-19", "2021-01-04"), ("2021-02-06", "2021-02-22"),
                  ("2021-04-10", "2021-04-26"), ("2021-05-13", "2021-05-17"), ("2021-07-06", "2021-09-02")),
    "2021-2022": (("2021-10-23", "2021-11-08"), ("2021-12-18", "2022-01-03"), ("2022-02-12", "2022-02-28"),
                  ("2022-04-16", "2022-05-02"), ("2022-05-26", "2022-05-30"), ("2022-07-07", "2022-09-01")),
    "2022-2023": (("2022-10-22", "2022-11-07"), ("2022-12-17", "2023-01-03"), ("2023-02-04", "2023-02-20"),
                  ("2023-04-08", "2023-04-24"), ("2023-05-18", "2023-05-22"), ("2023-07-08", "2023-09-04")),
    "2023-2024": (("2023-10-21", "2023-11-06"), ("2023-12-23", "2024-01-08"), ("2024-02-17", "2024-03-04"),
                  ("2024-04-13", "2024-04-29"), ("2024-05-09", "2024-05-13"), ("2024-07-06", "2024-09-02")),
    "2024-2025": (("2024-10-19", "2024-11-04"), ("2024-12-21", "2025-01-06"), ("2025-02-22", "2025-03-10"),
                  ("2025-04-19", "2025-05-05"), ("2025-05-29", "2025-06-02"), ("2025-07-05", "2025-09-01")),
    "2025-2026": (("2025-10-18", "2025-11-03"), ("2025-12-20", "2026-01-05"), ("2026-02-07", "2026-02-23"),
                  ("2026-04-04", "2026-04-20"), ("2026-05-14", "2026-05-18"), ("2026-07-04", "2026-09-01")),
}
SOURCE_VACANCES = ("vacances scolaires de la zone A (académie de Bordeaux) : jeu ouvert du ministère de "
                   "l'Éducation nationale fr-en-calendrier-scolaire (2017-2018 à 2025-2026), arrêtés du BO "
                   "(2015-2016, 2016-2017) ; règle type hors de la table")


def _d(s: str) -> date:
    return date.fromisoformat(s)


def paques(annee: int) -> date:
    """Dimanche de Pâques (calendrier grégorien, algorithme de Meeus/Jones/Butcher)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mois = (h + l_ - 7 * m + 114) // 31
    jour = (h + l_ - 7 * m + 114) % 31 + 1
    return date(annee, mois, jour)


@lru_cache(maxsize=64)
def jours_feries(annee: int) -> FrozenSet[date]:
    """Les 11 jours fériés de l'année (code du travail, art. L3133-1)."""
    p = paques(annee)
    return frozenset({
        date(annee, 1, 1), p + timedelta(days=1), date(annee, 5, 1), date(annee, 5, 8),
        p + timedelta(days=39), p + timedelta(days=50), date(annee, 7, 14), date(annee, 8, 15),
        date(annee, 11, 1), date(annee, 11, 11), date(annee, 12, 25),
    })


def feries_commerce(annee: int) -> FrozenSet[date]:
    """Les jours fériés où le commerce ferme (1er mai, 25 décembre, 1er janvier : hypothèse d'usage)."""
    return frozenset({date(annee, 1, 1), date(annee, 5, 1), date(annee, 12, 25)})


def _samedi_le_plus_proche(j: date) -> date:
    delta = (5 - j.weekday()) % 7
    return j + timedelta(days=delta) if delta <= 3 else j - timedelta(days=7 - delta)


def _vacances_regle_type(debut_annee_scolaire: int) -> Tuple[Tuple[date, date], ...]:
    """Une année scolaire hors de la table : la forme moyenne des années 2017-2018 à 2025-2026 (zone A).

    Toussaint : 16 jours depuis le samedi le plus proche du 19 octobre ; Noël : du samedi le plus proche du
    20 décembre au lundi qui suit le 1er janvier ; hiver : 16 jours depuis le samedi le plus proche du 14 février ;
    printemps : 16 jours depuis le samedi le plus proche du 12 avril ; été : du 5 juillet au 1er septembre."""
    a, b = debut_annee_scolaire, debut_annee_scolaire + 1
    t = _samedi_le_plus_proche(date(a, 10, 19))
    n = _samedi_le_plus_proche(date(a, 12, 20))
    j1 = date(b, 1, 1)
    reprise_noel = j1 + timedelta(days=(7 - j1.weekday()) % 7 or 7)
    h = _samedi_le_plus_proche(date(b, 2, 14))
    p = _samedi_le_plus_proche(date(b, 4, 12))
    return ((t, t + timedelta(days=16)), (n, reprise_noel), (h, h + timedelta(days=16)),
            (p, p + timedelta(days=16)), (date(b, 7, 5), date(b, 9, 1)))


@lru_cache(maxsize=64)
def vacances_zone_a(annee_civile: int) -> Tuple[Tuple[Tuple[date, date], ...], bool]:
    """Les périodes de vacances qui touchent l'année civile, et si toutes viennent de la table (sinon : règle
    type pour une partie)."""
    out: List[Tuple[date, date]] = []
    table = True
    for debut in (annee_civile - 1, annee_civile):
        cle = f"{debut}-{debut + 1}"
        if cle in _VACANCES_ZONE_A:
            out.extend((_d(x), _d(y)) for x, y in _VACANCES_ZONE_A[cle])
        else:
            table = False
            out.extend(_vacances_regle_type(debut))
    return tuple(out), table


def en_vacances_scolaires(j: date) -> bool:
    periodes, _ = vacances_zone_a(j.year)
    return any(a <= j < b for a, b in periodes)


def fuseau_du_pays(country_code: Optional[str]) -> str:
    return FUSEAU_PAR_PAYS.get(str(country_code or "").upper(), FUSEAU_DEFAUT)


@dataclass
class CalendrierHoraire:
    """Les horaires humains de chaque heure de la météo (même longueur que la série)."""
    heure: List[int]                 # heure des horaires humains (légale ou universelle selon `horaires_base`)
    semaine: List[int]               # jour de la semaine de la date de l'heure, 0 = lundi
    ouvre: List[bool]                # le jour de l'heure est ouvré pour le profil (True sans filtre de jours)
    dates: List[date]                # date (légale ou universelle) de l'heure
    jours_ouvres: Dict[date, bool] = field(default_factory=dict)
    infos: Dict[str, Any] = field(default_factory=dict)
    _ouvre_date: Any = field(default=None, repr=False)

    def ouvre_prepare(self, idx: int, fin_occupation_h: int) -> bool:
        """Le jour que l'heure prépare (le jour même avant la fin d'occupation, le lendemain après) est-il ouvré ?"""
        j = self.dates[idx]
        if self.heure[idx] >= int(fin_occupation_h):
            j = j + timedelta(days=1)
        if j in self.jours_ouvres:
            return self.jours_ouvres[j]
        return self._ouvre_date(j)


def _jour_ouvre(j: date, semaine: int, profil: str, filtre: bool, *, scolaire: str, commerce: str,
                feries: str) -> bool:
    if not filtre:
        return True
    dernier = 6 if (profil == "DAY6" and commerce == "lundi_samedi") else 5
    if semaine >= dernier:
        return False
    if feries == "feries":
        if j in (feries_commerce(j.year) if profil == "DAY6" else jours_feries(j.year)):
            return False
    if profil == "SCHOOL" and scolaire == "zone_a" and en_vacances_scolaires(j):
        return False
    return True


def calendrier_horaire(horodatages: Sequence[Any], annee: Optional[int], profil: Optional[str], filtre_jours: bool,
                       *, fuseau: str = FUSEAU_DEFAUT, horaires_base: str = "locale",
                       jours_semaine: str = "reels", scolaire: str = "zone_a",
                       commerce: str = "lundi_samedi", feries: str = "feries") -> CalendrierHoraire:
    """Le calendrier des horaires humains d'une série météo horaire.

    `horodatages` : ceux de la série météo (temps universel, naïfs ou non), ramenés à une année de référence
    au chargement (29 février écarté) : seuls le mois, le jour et l'heure sont lus. `annee` : l'année météo
    simulée (le vrai calendrier de cette année) ; None : 2020 (dit dans `infos`). `profil` : le profil
    d'occupation de l'usage (`building_types.OCCUPATION_PROFILES`). `filtre_jours` : le profil distingue des jours
    fermés (`days_per_year` < 365) ; sans filtre, tout jour est ouvré."""
    for nom, val, permis in (("horaires_base", horaires_base, HORAIRES_BASES),
                             ("calendrier_jours_semaine", jours_semaine, JOURS_SEMAINE),
                             ("calendrier_scolaire", scolaire, CALENDRIERS_SCOLAIRES),
                             ("calendrier_commerce", commerce, CALENDRIERS_COMMERCE),
                             ("calendrier_jours_feries", feries, JOURS_FERIES)):
        if val not in permis:
            raise ValueError(f"{nom} inconnu : {val!r} (attendu : {', '.join(permis)})")
    an = int(annee) if annee is not None else 2020
    profil = str(profil or "")
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(fuseau) if horaires_base == "locale" else timezone.utc
    heures: List[int] = []
    dates: List[date] = []
    semaine: List[int] = []
    ouvre: List[bool] = []
    jours: Dict[date, bool] = {}
    def _jour_moteur(j: date) -> int:
        # « jour0_lundi » : le rang du jour dans la série de 365 jours (29 février écarté), jour 0 = lundi.
        k = (date(2023, j.month, min(j.day, 28) if j.month == 2 else j.day) - date(2023, 1, 1)).days
        return k + 365 * (j.year - an)
    for ts in horodatages:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        utc = datetime(an, ts.month, ts.day, ts.hour, tzinfo=timezone.utc)
        loc = utc.astimezone(tz)
        j = loc.date()
        heures.append(loc.hour)
        dates.append(j)
        w = j.weekday() if jours_semaine == "reels" else _jour_moteur(j) % 7
        semaine.append(w)
        if j not in jours:
            jours[j] = _jour_ouvre(j, w, profil, filtre_jours, scolaire=scolaire, commerce=commerce, feries=feries)
        ouvre.append(jours[j])

    def _ouvre_date(j: date) -> bool:
        w = j.weekday() if jours_semaine == "reels" else _jour_moteur(j) % 7
        return _jour_ouvre(j, w, profil, filtre_jours, scolaire=scolaire, commerce=commerce, feries=feries)

    # Le 29 février est écarté de la météo : l'heure qui y tombe en heure légale (le 28 à 23 h UTC) ne compte pas un
    # jour de plus.
    n_jours_ouvres = sum(1 for j, o in jours.items() if o and j.year == an and not (j.month == 2 and j.day == 29))
    _, table = vacances_zone_a(an)
    infos: Dict[str, Any] = {
        "horaires_base": horaires_base,
        "fuseau": fuseau if horaires_base == "locale" else "UTC",
        "jours_semaine": jours_semaine,
        # Texte, pas nombre : une moyenne sur plusieurs années météo ne doit pas moyenner l'année du calendrier.
        "annee_calendrier": (str(an) if annee is not None else f"{an} (supposée)"),
        "filtre_jours": bool(filtre_jours),
        "jours_ouvres_an": (n_jours_ouvres if filtre_jours else None),
        "calendrier_scolaire": (scolaire if profil == "SCHOOL" and filtre_jours else None),
        "vacances_source": ((SOURCE_VACANCES + ("" if table else " ; RÈGLE TYPE pour cette année"))
                            if profil == "SCHOOL" and filtre_jours and scolaire == "zone_a" else None),
        "calendrier_commerce": (commerce if profil == "DAY6" and filtre_jours else None),
        "jours_feries": (feries if filtre_jours else None),
    }
    cal = CalendrierHoraire(heure=heures, semaine=semaine, ouvre=ouvre, dates=dates, jours_ouvres=jours,
                            infos=infos)
    cal._ouvre_date = _ouvre_date
    return cal
