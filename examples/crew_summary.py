"""Print aggregate crew validation data; network access requires --execute."""
import argparse
from getpass import getpass
from csr2cdn import CSR2Services


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("Dry run: zero network requests. Use --execute for your own account.")
        return
    with CSR2Services(getpass("PlayerID: "), allow_network=True) as api:
        print(api.get_crew_rp_snapshot().public_summary())


if __name__ == "__main__":
    main()
