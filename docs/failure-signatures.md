# Failure signatures (Module 2 capture lab)

Each entry is a **hypothesis until a capture proves it**. Status is `hypothesis` until you have
run the case, opened the pcap from `reports/artifacts/test_induced_failure_<case>/capture.pcap`,
and confirmed the frame sequence. Then change it to `confirmed`, fill in the real reason/status
codes, and add the Wireshark screenshot under `docs/img/`.

Capture point: `hwsim0` (radiotap + 802.11). WPA2 data frames are decrypted in Wireshark with
*Edit > Preferences > Protocols > IEEE 802.11 > Decryption keys* -> `wpa-pwd`
`labpassword123:lab-diag`.

Classifier stages, in join order: `network_selection`, `authentication`, `association`,
`key_exchange`, `dhcp`, `dns`, `success`
(plus `undetermined` when data is encrypted and no key was given).

---

## 1. Wrong passphrase (WPA2-PSK)

* **Induce:** client `psk="wrongpassword1"`, AP WPA2-PSK, PMF optional.
* **Expected stage:** `key_exchange`
* **Expected frames:** Auth (Open, status 0) -> Assoc Req/Resp (status 0) -> EAPOL M1 -> M2 ->
  (no M3; AP's MIC check on M2 fails) -> M1/M2 retries -> Deauth (reason 15, 4-way handshake
  timeout, or 2).
* **Filter:** `eapol || wlan.fc.type_subtype == 0x0c`
* **Observed:** _TBD_
* **Status:** hypothesis

## 2. Wrong password (WPA3-SAE)

* **Induce:** client `key_mgmt=SAE`, `sae_password="wrongpassword1"`, AP SAE with PMF required.
* **Expected stage:** `authentication`
* **Expected frames:** Auth SAE Commit (STA) -> Commit (AP) -> Confirm (STA) -> no Confirm from AP
  (confirm verification fails) -> retries. No association.
* **Filter:** `wlan.fixed.auth.alg == 3`
* **Observed:** _TBD_
* **Status:** hypothesis

## 3. WPA2-only client, WPA3-only AP

* **Induce:** client `key_mgmt=WPA-PSK`, `ieee80211w=0`; AP SAE, PMF required.
* **Expected stage:** `network_selection` (the client filters the AP out before sending any
  Authentication or Association frame)
* **Expected frames:** Probe Req/Resp only. wpa_supplicant finds no common AKM in the RSN IE
  (AKM suite 8 = SAE) and never sends Authentication.
* **Filter:** `wlan.fc.type_subtype == 0x04 || wlan.fc.type_subtype == 0x05`; inspect `wlan.rsn.akms.type`
* **Observed:** _TBD_
* **Status:** hypothesis

## 4. PMF mismatch

* **Induce:** AP WPA2-PSK `ieee80211w=2`; client `ieee80211w=0`.
* **Expected stage:** `network_selection`
* **Expected frames:** Probe Req/Resp; RSN Capabilities has MFPR=1. Client skips the BSS
  (no Auth). If a client did try, hostapd would reject the Assoc Req (status 31, "robust
  management frame policy violation"), and that variant would be classified `association`.
* **Filter:** `wlan.rsn.capabilities.mfpr == 1`
* **Observed:** _TBD_
* **Status:** hypothesis

## 5. MAC blocked

* **Induce:** client MAC in hostapd `deny_mac_file`.
* **Expected stage:** `network_selection` (changed from `authentication` after the first run)
* **Expected frames:** Probe Requests from the client with no Probe Response to it, and no
  Authentication frames at all. The AP stays silent towards the denied MAC, so the client
  never picks the network.
* **Filter:** `wlan.sa == <client MAC> || wlan.da == <client MAC>`
* **Observed (2026-09-27, first run):** classifier said `network_selection`: "client never
  attempted authentication or association". The last probe frames were four Probe Requests
  from the client to broadcast with no Probe Response, and no Authentication frames. Not yet
  cross-checked against the wpa_supplicant log or opened in Wireshark.
* **Other APs:** many vendors answer a blocked MAC with an Authentication Response carrying a
  non-zero status (e.g. 1, unspecified failure) instead; that is an `authentication` failure.
  The classifier handles both (unit test `test_mac_blocked_is_authentication`); the expected
  stage here is for hostapd.
* **Status:** observed once, pcap review pending

## 6. DHCP server down

* **Induce:** dnsmasq with DHCP disabled.
* **Expected stage:** `dhcp`
* **Expected frames:** full join (M1-M4) -> DHCP Discover repeated, no Offer.
* **Filter:** `dhcp` (with decryption on)
* **Observed (2026-09-27, first run):** dhclient log showed DHCPDISCOVER repeated with no
  Offer, as expected, but the test crashed: dhclient outlived the harness's subprocess
  timeout and `TimeoutExpired` was not caught. Fixed in `WifiClient.dhcp()`, which now
  treats the timeout as "no lease" and deletes old leases first. Re-run pending.
* **Status:** hypothesis

## 7. DNS broken

* **Induce:** dnsmasq with `port=0` (DNS off, DHCP still advertises it as the resolver).
* **Expected stage:** `dns`
* **Expected frames:** join + DHCP DORA -> DNS query for `gw.lab` -> ICMP port unreachable,
  no DNS response.
* **Filter:** `dns || icmp.type == 3`
* **Observed:** _TBD_
* **Status:** hypothesis

---

## 8. 802.1X wrong password / untrusted server (tests/test_enterprise.py)

* **Induce:** WPA2-Enterprise AP (hostapd built-in EAP server); client uses the wrong password
  (EAP-PWD or PEAP-MSCHAPv2), or trusts a different CA than the server certificate's.
* **Expected stage:** `eap` (after association, before the 4-way handshake)
* **Expected frames:** Open System auth OK -> association OK -> EAP Request/Response
  (Identity, then the method) -> EAP-Failure (code 4) from the AP; no EAPOL-Key frames.
  Untrusted server: TLS exchange inside EAP stops; client log has
  `CTRL-EVENT-EAP-TLS-CERT-ERROR`.
* **Filter:** `eap || eapol`
* **Observed:** _TBD_
* **Status:** hypothesis

---

## External validation (Wireshark wiki sample captures)

Run the classifier on public captures so it is not validated only on emulated data.
Download from <https://wiki.wireshark.org/SampleCaptures> (802.11 section) into `captures/external/`
(not committed), then:

```
python -m classifier.classify_join captures/external/wpa-Induction.pcap --wpa-pwd Induction:Coherer
```

| Capture | Ground truth | Classifier output | Correct? | Notes |
|---|---|---|---|---|
| wpa-Induction.pcap | successful WPA2-PSK join | _TBD_ | | |
| wpa-eap-tls.pcap.gz | 802.1X/EAP-TLS join | _TBD_ | | EAP is now modelled (`eap` stage); decrypting needs the PMK, which the sample page may not give |
| _add more_ | | | | |
