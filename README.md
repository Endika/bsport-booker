# bsport-booker

Books your [bsport](https://bsport.io/) classes on its own. Tell it which class you want and
on which days and hours. As soon as one of those classes is published, open, and payable with
one of your packs, it books it. It pings you on Slack about bookings, full classes, and
credits running low or out.

Run it from cron on a Raspberry Pi. It uses only the standard library, so any stock
`python3` from 3.11 up will do.

This is not an official client. It talks to the bsport API with your own member account, the
same way the web app does.

## What the API doesn't tell you

- **Logging in takes a plain email and password**, with no captcha:
  `POST platform/v1/authentication/signin/with-login/`. The token that comes back goes in
  `Authorization: Token …`. Accounts that sign in with Google or Apple can't use this.
- **You pay with a pack, not with "credits"**. Each pack (`consumer-payment-pack`) has its
  own dates and its own `available_credits`. A class can only be paid with a pack that covers
  the class day, so a new month's pack sitting at full credits is no use for a class on the
  last day of the old one. When two packs cover the day, the booker uses the one that
  expires first.
- **Booking is one call**:
  `POST buyable/v1/payment-pack/consumer-payment-pack/{pack}/register_booking/ {"offer": id}`.
- **Filtering the class list by `activity__in` returns nothing**, so the booker filters on the
  activity name itself.
- **A published class can be `available: false`**. Bank holidays look like this. The booker
  never books one.

## What a run does

For each published class that matches a `[[class]]` in your config and hasn't started yet:

| Situation | What it does | Slack |
|---|---|---|
| You're already booked | nothing | — |
| Open, with a pack to pay for it | books it | 🎉 once |
| Full | tries again next run and books it if a spot frees up | 🚫 once |
| No pack with credits for that day | skips it; this is not treated as a failure | ⚠️ once |
| The studio marked it unavailable | skips it | ⛔ once |
| Booking refused | exit 1 | ❌ once |

Packs at `low_credits` or below, or at zero, get one message each. Every message ends with
your credits line. A run with nothing new stays silent. When login or the network fails,
you're told once a day.

## Getting started

You need Python 3.11 or newer and a bsport account that logs in with an email and a password.

```sh
git clone https://github.com/Endika/bsport-booker && cd bsport-booker
mkdir -p ~/.config/bsport && chmod 700 ~/.config/bsport
read -rp 'Email: ' E; read -rsp 'Password: ' P; echo
umask 077; printf 'email=%s\npassword=%s\n' "$E" "$P" > ~/.config/bsport/credentials; unset E P
cp config.example.toml ~/.config/bsport/config.toml
```

Find your studio's ids and class names. bsport only tells a member which studios are theirs
through their upcoming bookings, so have at least one class booked.

```sh
python3 -m bsport_booker --config ~/.config/bsport/config.toml --discover
```

Put `company`, `establishment` and your `[[class]]` blocks in the config. Then look before you
book:

```sh
python3 -m bsport_booker --config ~/.config/bsport/config.toml --dry-run   # books nothing, tells nobody
python3 -m bsport_booker --config ~/.config/bsport/config.toml --status    # the full picture, to Slack
```

## Cron

Every 30 minutes. Classes get booked soon after they're published, and a quiet run logs in,
reads your member, packs, bookings and classes (five requests, more if a list runs to several
pages) and says nothing.

```cron
*/30 * * * * cd ~/bsport-booker && flock -n /tmp/bsport-booker.lock /usr/bin/python3 -m bsport_booker --config ~/.config/bsport/config.toml >> ~/bsport-booker/booker.log 2>&1
```

## Layout

Ports and adapters, with the decisions kept away from the plumbing:

```
domain/       offers, packs, wanted classes and the booking policy: pure, no I/O
ports.py      the bsport gateway, the notifier, the state store and the once-a-day gate
adapters/     bsport/ (API and parsing), slack.py, state.py (JSON file, daily marker), http.py
application/  the run, its gates, --status, --dry-run, --discover and the wording; no I/O
cli.py        argparse, the composition root, printing and exit codes
```

The domain says what to do with each class; the application does it and decides what is
worth a message. Every sentence you read on Slack lives in `application/messages.py`.

## Development

```sh
make install
make check   # ruff, format, mypy --strict, pytest
```

The tests run the real adapters against an in-memory bsport and an in-memory Slack. No mocks,
and nothing touches the network.

## License

[MIT](LICENSE)
