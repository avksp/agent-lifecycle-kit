def pytest_addoption(parser):
    parser.addoption("--operation-request", action="store", default=None)
