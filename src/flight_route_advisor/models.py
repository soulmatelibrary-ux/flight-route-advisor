"""Data models for airports and flights."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Airport:
    """Represents an airport.

    Attributes:
        code: IATA code (e.g. ``"LAX"``).
        name: Full airport name.
        city: City the airport serves.
        country: Country code (ISO 3166-1 alpha-2).
    """

    code: str
    name: str
    city: str
    country: str

    def __str__(self) -> str:
        return f"{self.code} ({self.city}, {self.country})"


@dataclass
class Flight:
    """Represents a direct flight between two airports.

    Attributes:
        origin: Departure airport IATA code.
        destination: Arrival airport IATA code.
        airline: Airline name or code.
        duration_minutes: Total flight duration in minutes.
        cost_usd: Approximate ticket price in USD.
        flight_number: Optional identifier for the flight.
    """

    origin: str
    destination: str
    airline: str
    duration_minutes: int
    cost_usd: float
    flight_number: str = ""

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must be non-negative")
        self.origin = self.origin.upper()
        self.destination = self.destination.upper()

    def __str__(self) -> str:
        hours, minutes = divmod(self.duration_minutes, 60)
        label = f" ({self.flight_number})" if self.flight_number else ""
        return (
            f"{self.origin} → {self.destination}{label} "
            f"[{self.airline}] {hours}h {minutes:02d}m  ${self.cost_usd:.2f}"
        )


@dataclass
class Route:
    """A complete route from origin to destination via zero or more stopovers.

    Attributes:
        flights: Ordered list of flights making up the route.
        total_cost_usd: Sum of all flight costs.
        total_duration_minutes: Sum of all flight durations (excludes layover time).
    """

    flights: list[Flight] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return sum(f.cost_usd for f in self.flights)

    @property
    def total_duration_minutes(self) -> int:
        return sum(f.duration_minutes for f in self.flights)

    @property
    def stops(self) -> int:
        """Number of intermediate stops (connections)."""
        return max(0, len(self.flights) - 1)

    @property
    def origin(self) -> str | None:
        return self.flights[0].origin if self.flights else None

    @property
    def destination(self) -> str | None:
        return self.flights[-1].destination if self.flights else None

    def __str__(self) -> str:
        if not self.flights:
            return "(empty route)"
        path = " → ".join(
            [self.flights[0].origin] + [f.destination for f in self.flights]
        )
        hours, minutes = divmod(self.total_duration_minutes, 60)
        stops_label = f"{self.stops} stop(s)" if self.stops else "non-stop"
        return (
            f"{path}  |  {stops_label}  |  "
            f"{hours}h {minutes:02d}m  |  ${self.total_cost_usd:.2f}"
        )
