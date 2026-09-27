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
* **Expected stage:** `authentication`
* **Expected frames:** Auth Req (Open) -> Auth Resp with non-zero status (expected 1,
  unspecified failure), repeated.
* **Filter:** `wlan.fc.type_subtype == 0x0b && wlan.fixed.status_code != 0`
* **Observed:** _TBD_
* **Status:** hypothesis

## 6. DHCP server down

* **Induce:** dnsmasq with DHCP disabled.
* **Expected stage:** `dhcp`
* **Expected frames:** full join (M1-M4) -> DHCP Discover repeated, no Offer.
* **Filter:** `dhcp` (with decryption on)
* **Observed:** _TBD_
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
| wpa-eap-tls.pcap.gz | 802.1X/EAP-TLS join | _TBD_ | | EAP stages are not modelled; expect a gap |
| _add more_ | | | | |
