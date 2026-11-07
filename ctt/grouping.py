"""Assigning each file to Animal / Uncertain / Human-Vehicle / Empty.

Groups are computed on the fly from stored detector scores and the project's
thresholds, so moving a threshold slider updates everything instantly.
"""

ANIMAL = "animal"
UNCERTAIN = "uncertain"
HUMAN = "human"
EMPTY = "empty"

GROUPS = [ANIMAL, UNCERTAIN, HUMAN, EMPTY]
GROUP_LABELS = {
    ANIMAL: "Animal",
    UNCERTAIN: "Uncertain",
    HUMAN: "Human / Vehicle",
    EMPTY: "Empty",
}


def classify(max_animal, max_person, max_vehicle, animal_thr=0.20, uncertain_thr=0.05, manual=None):
    """Return the group for one file.

    - manual override (set by the user) always wins
    - animal score >= animal_thr                      -> Animal
    - person/vehicle score >= animal_thr              -> Human / Vehicle
    - any score between uncertain_thr and animal_thr  -> Uncertain
    - otherwise                                       -> Empty
    Files not yet processed (scores None) return None.
    """
    if manual:
        return manual
    if max_animal is None:
        return None
    a = max_animal or 0.0
    hv = max(max_person or 0.0, max_vehicle or 0.0)
    if a >= animal_thr:
        return ANIMAL
    if hv >= animal_thr:
        return HUMAN
    if max(a, hv) >= uncertain_thr:
        return UNCERTAIN
    return EMPTY


def sql_group_expr(animal_thr: float, uncertain_thr: float) -> str:
    """SQL CASE expression equivalent to classify(), for filtering in queries."""
    a, u = float(animal_thr), float(uncertain_thr)
    return (
        "CASE"
        " WHEN m.manual_group IS NOT NULL THEN m.manual_group"
        " WHEN m.max_animal IS NULL THEN NULL"
        f" WHEN m.max_animal >= {a} THEN 'animal'"
        f" WHEN MAX(IFNULL(m.max_person,0), IFNULL(m.max_vehicle,0)) >= {a} THEN 'human'"
        f" WHEN MAX(m.max_animal, IFNULL(m.max_person,0), IFNULL(m.max_vehicle,0)) >= {u} THEN 'uncertain'"
        " ELSE 'empty' END"
    )
