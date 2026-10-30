import os

import pytest
from dotenv import load_dotenv


@pytest.fixture(scope="session", autouse=True)
def load_environment():
    load_dotenv(override=False)
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
