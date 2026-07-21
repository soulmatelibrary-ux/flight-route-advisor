"""High-level advisor API that wraps the RouteGraph."""

from __future__ import annotations

from .data import AIRPORTS, FLIGHTS
from .graph import OptimizeBy, RouteGraph
from .models import Airport, Flight, Route


class FlightRouteAdvisor:
    """Convenience wrapper around :class:`RouteGraph` with pre-loaded data.

    You can use the default sample dataset or supply your own airports and
    flights when constructing the advisor.

    Example::

        advisor = FlightRouteAdvisor()
        routes = advisor.recommend("JFK", "SIN", optimize_by="cost")
        for route in routes[:3]:
            print(route)
    """

    def __init__(
        self,
        airports: list[Airport] | None = None,
        flights: list[Flight] | None = None,
    ) -> None:
        self._graph = RouteGraph()
        for airport in airports if airports is not None else AIRPORTS:
            self._graph.add_airport(airport)
        for flight in flights if flights is not None else FLIGHTS:
            self._graph.add_flight(flight)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_airports(self) -> list[Airport]:
        """Return all airports known to the advisor, sorted by IATA code."""
        return self._graph.airports()

    def direct_flights(self, origin: str) -> list[Flight]:
        """Return all direct flights departing from *origin*."""
        return self._graph.flights_from(origin)

    def recommend(
        self,
        origin: str,
        destination: str,
        optimize_by: OptimizeBy = "cost",
        max_stops: int = 2,
        top_n: int = 5,
    ) -> list[Route]:
        """Return up to *top_n* recommended routes.

        Args:
            origin: Departure airport IATA code.
            destination: Arrival airport IATA code.
            optimize_by: Optimisation criterion –
                ``"cost"`` (default), ``"duration"``, or ``"stops"``.
            max_stops: Maximum number of intermediate stops (default 2).
            top_n: Maximum number of results to return (default 5).

        Returns:
            List of :class:`Route` objects sorted by the chosen criterion.
        """
        routes = self._graph.find_routes(
            origin=origin,
            destination=destination,
            optimize_by=optimize_by,
            max_stops=max_stops,
        )
        return routes[:top_n]
