"""Tests for the CLI entry point."""

import pytest

from flight_route_advisor.cli import main


class TestCLISearch:
    def test_search_returns_zero(self, capsys):
        rc = main(["search", "JFK", "LHR"])
        assert rc == 0

    def test_search_output_contains_airports(self, capsys):
        main(["search", "JFK", "LHR"])
        out = capsys.readouterr().out
        assert "JFK" in out
        assert "LHR" in out

    def test_search_optimize_duration(self, capsys):
        rc = main(["search", "JFK", "LHR", "--optimize", "duration"])
        assert rc == 0

    def test_search_optimize_stops(self, capsys):
        rc = main(["search", "JFK", "LHR", "--optimize", "stops"])
        assert rc == 0

    def test_search_max_stops_zero_nonstop_only(self, capsys):
        rc = main(["search", "JFK", "LHR", "--max-stops", "0"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "non-stop" in out

    def test_search_no_route_returns_zero(self, capsys):
        # LAX to JFK with 0 stops should still work (direct flight exists)
        rc = main(["search", "LAX", "JFK", "--max-stops", "0"])
        # No direct LAX→JFK in dataset, but still returns 0
        assert rc == 0

    def test_search_unknown_airport_returns_one(self, capsys):
        rc = main(["search", "ZZZ", "LHR"])
        assert rc == 1

    def test_search_top_n(self, capsys):
        main(["search", "JFK", "LHR", "--top", "2"])
        out = capsys.readouterr().out
        # At most 2 results listed (numbered #1 and #2, no #3)
        assert "#1" in out
        assert "#3" not in out

    def test_search_top_n_default_five(self, capsys):
        rc = main(["search", "JFK", "SIN", "--top", "5"])
        assert rc == 0


class TestCLIAirports:
    def test_airports_returns_zero(self, capsys):
        rc = main(["airports"])
        assert rc == 0

    def test_airports_output_contains_header(self, capsys):
        main(["airports"])
        out = capsys.readouterr().out
        assert "Code" in out
        assert "City" in out

    def test_airports_output_contains_known_code(self, capsys):
        main(["airports"])
        out = capsys.readouterr().out
        assert "JFK" in out
        assert "LHR" in out


class TestCLIFlights:
    def test_flights_returns_zero(self, capsys):
        rc = main(["flights", "JFK"])
        assert rc == 0

    def test_flights_output_contains_origin(self, capsys):
        main(["flights", "JFK"])
        out = capsys.readouterr().out
        assert "JFK" in out

    def test_flights_unknown_airport_no_error(self, capsys):
        rc = main(["flights", "ZZZ"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No direct flights" in out
