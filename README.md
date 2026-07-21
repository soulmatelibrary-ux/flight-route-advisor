# Flight Route Advisor

A command-line tool that finds optimal flight routes between airports using Dijkstra's shortest-path algorithm. Routes can be optimised by **cost**, **total duration**, or **number of stops**.

## Features

- 25 airports across North America, Europe, the Middle East, Asia, and Australia
- 100+ sample direct flights with realistic durations and prices
- Three optimisation modes: cheapest fare, fastest journey, or fewest connections
- Configurable maximum stops and number of results to display
- Clean, extensible Python API for programmatic use

## Requirements

- Python 3.10 or later

## Installation

```bash
pip install -e .
```

To also install development/testing dependencies:

```bash
pip install -e ".[dev]"
```

## CLI Usage

### Search for routes

```
flight-route-advisor search <ORIGIN> <DESTINATION> [options]
```

| Option | Default | Description |
|---|---|---|
| `--optimize` | `cost` | Optimisation criterion: `cost`, `duration`, or `stops` |
| `--max-stops` | `2` | Maximum number of intermediate connections |
| `--top` | `5` | Number of results to display |

**Examples:**

```bash
# Cheapest routes from New York to Singapore (up to 2 stops)
flight-route-advisor search JFK SIN

# Fastest route from Atlanta to Sydney
flight-route-advisor search ATL SYD --optimize duration

# Fewest-stop routes, at most 1 connection
flight-route-advisor search LAX LHR --optimize stops --max-stops 1

# Show up to 3 results
flight-route-advisor search JFK SIN --top 3
```

### List all airports

```bash
flight-route-advisor airports
```

### List direct flights from an airport

```bash
flight-route-advisor flights JFK
```

## Python API

```python
from flight_route_advisor import FlightRouteAdvisor

advisor = FlightRouteAdvisor()

# Get top 3 cheapest routes
routes = advisor.recommend("JFK", "SIN", optimize_by="cost", top_n=3)
for route in routes:
    print(route)

# Use your own data
from flight_route_advisor.models import Airport, Flight

custom_airports = [
    Airport("AAA", "Alpha Airport", "Alpha City", "XX"),
    Airport("BBB", "Beta Airport",  "Beta City",  "XX"),
]
custom_flights = [
    Flight("AAA", "BBB", "MyAir", duration_minutes=90, cost_usd=150.0),
]
advisor = FlightRouteAdvisor(airports=custom_airports, flights=custom_flights)
routes = advisor.recommend("AAA", "BBB")
```

## Running Tests

```bash
pytest
```
