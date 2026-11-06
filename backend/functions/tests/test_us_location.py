"""USA-only rule, using location formats seen on the live boards."""
import pytest

from job_alerts.filters import is_us_job


@pytest.mark.parametrize(
    "location",
    [
        "Idaho - Boise",
        "Washington - Pullman",
        "North Carolina - Charlotte",
        "United States, Multiple Locations, Multiple Locations",
        "United States of America, Washington, Liberty Lake",
        "USA, TN, Chattanooga, Remote",
        "Lafayette, IN, US",
        "Alpharetta, GA, USA",
        "Edwardsville, Illinois",
        "Atlanta, GA 30301",
        "Remote",
        "Chicago, IL (Local Office)",
    ],
)
def test_us_locations_pass(location):
    assert is_us_job([location])


@pytest.mark.parametrize(
    "location",
    [
        "Rep of Georgia - Tbilisi",
        "Mexico - Mexico City",
        "Mexico - San Luis Potosi",
        "India - Bengaluru",
        "India, Bangalore",
        "Noida, UP",
        "Noida, UP, IN",
        "Toronto, ON, CA",
        "London, GBR",
        "Canada - Burnaby",
        "Italy - Milan",
        "Manila, Manila, Philippines",
        "Australia - Melbourne",
        "UAE - Dubai Silicon Oasis",
        "Remote, Canada",
    ],
)
def test_foreign_locations_fail(location):
    assert not is_us_job([location])


def test_any_us_location_is_enough():
    assert is_us_job(["India - Thane", "Texas - Houston"])


def test_no_stated_location_passes():
    assert is_us_job([]) and is_us_job([""])
