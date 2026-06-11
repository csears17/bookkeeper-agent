def test_package_imports():
    import bookkeeper_agent

    assert bookkeeper_agent.__version__ == "0.1.0"
