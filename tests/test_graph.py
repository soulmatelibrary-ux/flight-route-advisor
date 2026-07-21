"""Tests for RouteGraph pathfinding."""

import pytest

from flight_route_advisor.graph import RouteGraph
from flight_route_advisor.models import Airport, Flight


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def small_graph() -> RouteGraph:
    """A tiny graph:
        A --100min/$50--> B
        A --200min/$30--> C
        B --100min/$50--> C
        B --200min/$80--> D
        C --100min/$40--> D
    """
    g = RouteGraph()
    for code, city in [("A", "Alpha"), ("B", "Beta"), ("C", "Gamma"), ("D", "Delta")]:
        g.add_airport(Airport(code, f"{city} Airport", city, "XX"))

    g.add_flight(Flight("A", "B", "Air", 100, 50.00, "AB1"))
    g.add_flight(Flight("A", "C", "Air", 200, 30.00, "AC1"))
    g.add_flight(Flight("B", "C", "Air", 100, 50.00, "BC1"))
    g.add_flight(Flight("B", "D", "Air", 200, 80.00, "BD1"))
    g.add_flight(Flight("C", "D", "Air", 100, 40.00, "CD1"))
    return g


# ---------------------------------------------------------------------------
# add_airport / add_flight validation
# ---------------------------------------------------------------------------

class TestGraphMutators:
    def test_add_unknown_origin_raises(self):
        g = RouteGraph()
        g.add_airport(Airport("A", "Alpha", "Alpha", "XX"))
        with pytest.raises(ValueError, match="Unknown origin"):
            g.add_flight(Flight("Z", "A", "Air", 60, 100))

    def test_add_unknown_destination_raises(self):
        g = RouteGraph()
        g.add_airport(Airport("A", "Alpha", "Alpha", "XX"))
        with pytest.raises(ValueError, match="Unknown destination"):
            g.add_flight(Flight("A", "Z", "Air", 60, 100))

    def test_airports_sorted(self, small_graph):
        codes = [ap.code for ap in small_graph.airports()]
        assert codes == sorted(codes)

    def test_flights_from(self, small_graph):
        flights = small_graph.flights_from("A")
        assert len(flights) == 2
        destinations = {f.destination for f in flights}
        assert destinations == {"B", "C"}

    def test_flights_from_unknown_returns_empty(self, small_graph):
        assert small_graph.flights_from("Z") == []


# ---------------------------------------------------------------------------
# find_routes – basic connectivity
# ---------------------------------------------------------------------------

class TestFindRoutes:
    def test_direct_route_exists(self, small_graph):
        routes = small_graph.find_routes("A", "B")
        assert any(r.stops == 0 for r in routes)

    def test_no_route_returns_empty(self, small_graph):
        # D has no outgoing edges
        routes = small_graph.find_routes("D", "A")
        assert routes == []

    def test_unknown_origin_raises(self, small_graph):
        with pytest.raises(ValueError, match="Unknown origin"):
            small_graph.find_routes("Z", "A")

    def test_unknown_destination_raises(self, small_graph):
        with pytest.raises(ValueError, match="Unknown destination"):
            small_graph.find_routes("A", "Z")

    def test_max_stops_limits_results(self, small_graph):
        routes = small_graph.find_routes("A", "D", max_stops=0)
        # No direct A→D edge, so result should be empty
        assert routes == []

    def test_max_stops_one_allows_one_hop(self, small_graph):
        routes = small_graph.find_routes("A", "D", max_stops=1)
        # A→B→D (1 stop) or A→C→D (1 stop) should be found
        assert len(routes) >= 1
        assert all(r.stops <= 1 for r in routes)


# ---------------------------------------------------------------------------
# find_routes – optimise by cost
# ---------------------------------------------------------------------------

class TestOptimiseByCost:
    def test_cheapest_route_first(self, small_graph):
        routes = small_graph.find_routes("A", "D", optimize_by="cost")
        # A→C→D costs $30+$40=$70; A→B→D costs $50+$80=$130
        assert routes[0].total_cost_usd == pytest.approx(70.0)

    def test_sorted_ascending(self, small_graph):
        routes = small_graph.find_routes("A", "D", optimize_by="cost")
        costs = [r.total_cost_usd for r in routes]
        assert costs == sorted(costs)


# ---------------------------------------------------------------------------
# find_routes – optimise by duration
# ---------------------------------------------------------------------------

class TestOptimiseByDuration:
    def test_fastest_route_first(self, small_graph):
        routes = small_graph.find_routes("A", "D", optimize_by="duration")
        # A→B→D: 100+200=300 min; A→C→D: 200+100=300 min (tie)
        # A→B→C→D if max_stops allows it: 100+100+100=300 min (same)
        assert routes[0].total_duration_minutes <= 300

    def test_sorted_ascending(self, small_graph):
        routes = small_graph.find_routes("A", "D", optimize_by="duration")
        durations = [r.total_duration_minutes for r in routes]
        assert durations == sorted(durations)


# ---------------------------------------------------------------------------
# find_routes – optimise by stops
# ---------------------------------------------------------------------------

class TestOptimiseByStops:
    def test_fewest_stops_first(self, small_graph):
        routes = small_graph.find_routes("A", "D", optimize_by="stops", max_stops=2)
        stops = [r.stops for r in routes]
        assert stops == sorted(stops)

    def test_no_direct_flight_returns_one_stop(self, small_graph):
        routes = small_graph.find_routes("A", "D", optimize_by="stops", max_stops=1)
        assert all(r.stops <= 1 for r in routes)


# ---------------------------------------------------------------------------
# Cycle prevention
# ---------------------------------------------------------------------------

class TestCyclePrevention:
    def test_no_cyclic_routes(self):
        """Graph with a cycle should not produce infinite loops."""
        g = RouteGraph()
        for code in ["X", "Y", "Z"]:
            g.add_airport(Airport(code, f"{code} Airport", code, "XX"))
        g.add_flight(Flight("X", "Y", "Air", 60, 50))
        g.add_flight(Flight("Y", "Z", "Air", 60, 50))
        g.add_flight(Flight("Z", "Y", "Air", 60, 50))  # cycle Y↔Z
        routes = g.find_routes("X", "Z")
        assert len(routes) >= 1
        for route in routes:
            path = [route.origin] + [f.destination for f in route.flights]
            assert len(path) == len(set(path)), "Cycle detected in route"
