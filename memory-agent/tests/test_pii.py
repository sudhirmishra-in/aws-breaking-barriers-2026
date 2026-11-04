from producer_exchange.safety.pii import ComprehendPiiDetector


class _Client:
    def __init__(self, entities=None, error=None):
        self._entities = entities or []
        self._error = error
        self.calls = 0

    def detect_pii_entities(self, Text, LanguageCode):
        self.calls += 1
        if self._error:
            raise self._error
        return {"Entities": self._entities}


def _detector(client):
    detector = ComprehendPiiDetector.__new__(ComprehendPiiDetector)
    detector._client = client
    return detector


def _entity(text, span, kind, score=0.99):
    begin = text.index(span)
    return {"Type": kind, "Score": score, "BeginOffset": begin, "EndOffset": begin + len(span)}


def test_named_person_and_phone_are_flagged():
    text = "Carlos Ramírez, 312 555 0199"
    client = _Client([_entity(text, "Carlos Ramírez", "NAME"), _entity(text, "312 555 0199", "PHONE")])
    assert _detector(client).scan(text, "es", 3).entity_types == ["NAME", "PHONE"]


def test_a_bare_region_name_is_not_flagged_but_a_street_address_is():
    region = "estamos en Piura"
    assert _detector(_Client([_entity(region, "Piura", "ADDRESS")])).scan(region, "es", 1) is None
    street = "vivo en Calle 5 #12"
    flag = _detector(_Client([_entity(street, "Calle 5 #12", "ADDRESS")])).scan(street, "es", 1)
    assert flag.entity_types == ["ADDRESS"]


def test_dates_ages_and_low_confidence_matches_are_ignored():
    text = "hace 2 temporadas, tengo 40 años"
    entities = [_entity(text, "2 temporadas", "DATE_TIME"), _entity(text, "40 años", "AGE"), _entity(text, "tengo", "NAME", 0.2)]
    assert _detector(_Client(entities)).scan(text, "es", 1) is None


def test_languages_comprehend_cannot_scan_are_recorded_rather_than_treated_as_clean():
    client = _Client()
    flag = _detector(client).scan("Bonjour", "fr", 1)
    assert flag.scan_status == "unsupported_language"
    assert client.calls == 0


def test_a_failed_scan_is_recorded_and_does_not_break_the_turn():
    from botocore.exceptions import EndpointConnectionError

    client = _Client(error=EndpointConnectionError(endpoint_url="x"))
    assert _detector(client).scan("hola", "es", 1).scan_status == "failed"
