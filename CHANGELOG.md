# Changelog

## 0.1.0 (2026-09-26)


### Features

* book bsport classes on their own as soon as they can be booked ([1cb1d09](https://github.com/Endika/bsport-booker/commit/1cb1d09bc066962117f9ecce5988f4a61d7f67a8))


### Bug Fixes

* follow the offer list's links.next and refuse a list shorter than its count ([2edf63d](https://github.com/Endika/bsport-booker/commit/2edf63db874f27bd4597c062564a409352f851e9))
* gate the unsaved-state warning to once a day by a temp marker, not the 08:00 run ([b7952a5](https://github.com/Endika/bsport-booker/commit/b7952a58a226270c6884ac0c76d5ad58388dbf0e))
* keep the state file private even over a leftover temp file ([cf58466](https://github.com/Endika/bsport-booker/commit/cf5846648b09fda6630efc0a2bb31b7b837f328e))
* leave a corrupt state in place on a look and only report it ([2615478](https://github.com/Endika/bsport-booker/commit/2615478b0bd40959e2bf96c9b1333ec0c0f5c998))
* name a failure by its type when it carries no message ([58d70d6](https://github.com/Endika/bsport-booker/commit/58d70d667205fc652edfa4a030951d1642e93625))
* never spam or go silent on a broken state, Slack or credentials, and read odd bsport shapes ([807e52f](https://github.com/Endika/bsport-booker/commit/807e52f616759bccf7ca99cae8a984e40e68e6ca))
* read the unpaginated pack list and drop the past-bookings route bsport lacks ([bcf412c](https://github.com/Endika/bsport-booker/commit/bcf412cab946a61fc0b41d005e48907680291621))
* refuse redirects so a 3xx never passes for a booking ([1668ef8](https://github.com/Endika/bsport-booker/commit/1668ef8443f48a72d5ff86a6608f5590cbba6e34))
* say how far your own classes are published, not the whole studio ([092e193](https://github.com/Endika/bsport-booker/commit/092e193ca30cec879ddfc738fac55b7fc50100f6))
* show discovered class times on the studio's wall clock ([25ceb86](https://github.com/Endika/bsport-booker/commit/25ceb86913ba5fe6b04a26d474361ebea24a8474))
* show the real balance on a look while still spending credits for its decisions ([edf7b9c](https://github.com/Endika/bsport-booker/commit/edf7b9c8dac91ce8e88526e86ed9c7ae9d799c63))
* spend credits within a dry run or status as a real run would ([d7ce30d](https://github.com/Endika/bsport-booker/commit/d7ce30d4e5a42e12fa9548e707558decf586551a))


### Documentation

* count a quiet run's requests right and match the flattened layout ([bbe08f7](https://github.com/Endika/bsport-booker/commit/bbe08f7c205856f017c493ef735622c77d71c2b5))
* describe the layout ([eac9328](https://github.com/Endika/bsport-booker/commit/eac9328321cf36a5862eab4cb859a72cd1406751))
