"""Tests for FlightRouteAdvisor (integration-level)."""

import pytest

from flight_route_advisor import FlightRouteAdvisor
from flight_route_advisor.models import Airport, Flight


class TestAdvisorWithSampleData:
    def test_list_airports_returns_sorted_list(self):
        advisor = FlightRouteAdvisor()
        airports = advisor.list_airports()
        assert len(airports) > 0
        codes = [a.code for a in airports]
        assert codes == sorted(codes)

    def test_direct_flights_jfk(self):
        advisor = FlightRouteAdvisor()
        flights = advisor.direct_flights("JFK")
        assert len(flights) > 0
        assert all(f.origin == "JFK" for f in flights)

    def test_direct_flights_unknown_returns_empty(self):
        advisor = FlightRouteAdvisor()
        assert advisor.direct_flights("ZZZ") == []

    def test_recommend_jfk_lhr_returns_routes(self):
        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("JFK", "LHR")
        assert len(routes) > 0

    def test_recommend_nonstop_jfk_lhr(self):
        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("JFK", "LHR", optimize_by="cost")
        # There is a direct JFK→LHR flight in the sample data
        nonstop = [r for r in routes if r.stops == 0]
        assert len(nonstop) > 0

    def test_recommend_sorted_by_cost(self):
        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("JFK", "SIN", optimize_by="cost")
        costs = [r.total_cost_usd for r in routes]
        assert costs == sorted(costs)

    def test_recommend_sorted_by_duration(self):
        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("JFK", "SIN", optimize_by="duration")
        durations = [r.total_duration_minutes for r in routes]
        assert durations == sorted(durations)

    def test_recommend_sorted_by_stops(self):
        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("LAX", "SYD", optimize_by="stops")
        stops = [r.stops for r in routes]
        assert stops == sorted(stops)

    def test_recommend_top_n_respected(self):
        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("JFK", "SIN", top_n=2)
        assert len(routes) <= 2

    def test_recommend_max_stops_respected(self):
        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("JFK", "SYD", max_stops=1)
        assert all(r.stops <= 1 for r in routes)

    def test_recommend_no_route_returns_empty(self):
        advisor = FlightRouteAdvisor()
        # Use custom minimal data with no path
        custom_airports = [
            Airport("AA", "Airport AA", "City AA", "XX"),
            Airport("BB", "Airport BB", "City BB", "XX"),
        ]
        custom_flights = [Flight("AA", "BB", "Air", 60, 100)]
        adv = FlightRouteAdvisor(airports=custom_airports, flights=custom_flights)
        routes = adv.recommend("BB", "AA")
        assert routes == []

    def test_custom_data_overrides_defaults(self):
        custom_airports = [
            Airport("X1", "Airport X1", "City X1", "XX"),
            Airport("X2", "Airport X2", "City X2", "XX"),
        ]
        custom_flights = [Flight("X1", "X2", "TestAir", 90, 150.00, "T1")]
        adv = FlightRouteAdvisor(airports=custom_airports, flights=custom_flights)
        routes = adv.recommend("X1", "X2")
        assert len(routes) == 1
        assert routes[0].flights[0].airline == "TestAir"
