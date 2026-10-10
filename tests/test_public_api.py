def test_all_public_exports_exist():
    import csr2cdn

    for name in csr2cdn.__all__:
        assert hasattr(csr2cdn, name), name
