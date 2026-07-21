"""Tests for data models."""

import pytest

from flight_route_advisor.models import Airport, Flight, Route


class TestAirport:
    def test_str(self):
        ap = Airport("JFK", "John F. Kennedy International", "New York", "US")
        assert str(ap) == "JFK (New York, US)"

    def test_frozen(self):
        ap = Airport("LAX", "Los Angeles International", "Los Angeles", "US")
        with pytest.raises((AttributeError, TypeError)):
            ap.code = "SFO"  # type: ignore[misc]


class TestFlight:
    def test_normalises_codes_to_upper(self):
        f = Flight("jfk", "lhr", "British Airways", 415, 549.00, "BA178")
        assert f.origin == "JFK"
        assert f.destination == "LHR"

    def test_str_contains_key_info(self):
        f = Flight("JFK", "LHR", "British Airways", 415, 549.00, "BA178")
        s = str(f)
        assert "JFK" in s
        assert "LHR" in s
        assert "549.00" in s
        assert "BA178" in s

    def test_str_without_flight_number(self):
        f = Flight("JFK", "LHR", "British Airways", 415, 549.00)
        s = str(f)
        assert "JFK" in s
        assert "LHR" in s

    def test_negative_duration_raises(self):
        with pytest.raises(ValueError, match="duration_minutes must be positive"):
            Flight("JFK", "LHR", "BA", -10, 100)

    def test_zero_duration_raises(self):
        with pytest.raises(ValueError):
            Flight("JFK", "LHR", "BA", 0, 100)

    def test_negative_cost_raises(self):
        with pytest.raises(ValueError, match="cost_usd must be non-negative"):
            Flight("JFK", "LHR", "BA", 415, -1)

    def test_zero_cost_allowed(self):
        f = Flight("JFK", "LHR", "BA", 415, 0)
        assert f.cost_usd == 0


class TestRoute:
    def _make_route(self) -> Route:
        f1 = Flight("JFK", "LHR", "BA", 415, 549.00, "BA178")
        f2 = Flight("LHR", "SIN", "SQ", 775, 699.00, "SQ306")
        return Route(flights=[f1, f2])

    def test_total_cost(self):
        route = self._make_route()
        assert route.total_cost_usd == pytest.approx(1248.00)

    def test_total_duration(self):
        route = self._make_route()
        assert route.total_duration_minutes == 1190

    def test_stops(self):
        route = self._make_route()
        assert route.stops == 1

    def test_stops_nonstop(self):
        route = Route(flights=[Flight("JFK", "LHR", "BA", 415, 549.00)])
        assert route.stops == 0

    def test_origin_destination(self):
        route = self._make_route()
        assert route.origin == "JFK"
        assert route.destination == "SIN"

    def test_empty_route(self):
        route = Route()
        assert route.origin is None
        assert route.destination is None
        assert route.stops == 0
        assert str(route) == "(empty route)"

    def test_str_contains_path(self):
        route = self._make_route()
        s = str(route)
        assert "JFK" in s
        assert "LHR" in s
        assert "SIN" in s
        assert "1 stop(s)" in s

    def test_nonstop_str(self):
        route = Route(flights=[Flight("JFK", "LHR", "BA", 415, 549.00)])
        assert "non-stop" in str(route)
