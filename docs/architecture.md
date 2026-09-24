# Architecture

```mermaid
flowchart LR
    subgraph VM["Ubuntu 24.04 VM"]
        subgraph root["root namespace"]
            hostapd["hostapd<br/>ap0 (hwsim radio 0)"]
            dnsmasq["dnsmasq<br/>DHCP + DNS"]
            hwsim0["hwsim0<br/>monitor: every frame"]
            dumpcap["dumpcap -> pcap"]
            pytest["pytest harness<br/>testbed/ + classifier/"]
            br["br-lab (vlan_filtering)<br/>br-lab.10/.20/.30 + nftables<br/>(Module 3 only)"]
        end
        subgraph ns1["ns-client1"]
            s1["wpa_supplicant + dhclient<br/>sta1"]
        end
        subgraph ns2["ns-client2"]
            s2["sta2"]
        end
        subgraph ns3["ns-client3"]
            s3["sta3"]
        end
        air(("mac80211_hwsim<br/>emulated air"))
    end
    subgraph Host["Host OS"]
        emu["Android Emulator<br/>(AndroidWifi)"]
        adb["pytest -m android<br/>testbed/android.py"]
    end

    hostapd --- air
    s1 --- air
    s2 --- air
    s3 --- air
    air --> hwsim0 --> dumpcap
    hostapd --- dnsmasq
    hostapd -. "Module 3" .- br
    pytest --> hostapd & dnsmasq & dumpcap
    pytest -->|ip netns exec| s1 & s2 & s3
    adb -->|ADB| emu
```

## Why namespaces

Each client radio lives in its own network namespace. Without that, the kernel would route
client-to-AP traffic over loopback, skipping the emulated air, DHCP and the 802.11 data path.
With it, a client's only route out is its `staN` interface.

## Data flow of one test

1. `hostap.ensure()` renders `configs/hostapd/ap.conf.j2` and starts hostapd on `ap0`.
2. The `capture` fixture starts `dumpcap` on `hwsim0` for the test.
3. `WifiClient.join()` renders `configs/wpa_supplicant/client.conf.j2`, starts wpa_supplicant in
   the client's namespace, waits for `COMPLETED`, then runs dhclient, `dig`, `ping`.
4. Logs + pcap are copied to `reports/artifacts/<test>/` and linked from the HTML report.
5. Module 2 runs `classifier/classify_join.py` on the pcap and asserts the stage.

## Module 3 topology

```
 sta (lab-mgmt)   sta (lab-test)   sta (lab-iot)
       |                |                |
      ap0            ap0v20           ap0v30        <- one BSS per SSID (hostapd bss=)
       | PVID 10        | PVID 20        | PVID 30
       +--------------- br-lab ----------+          <- VLAN-filtering bridge = managed switch
                          |
          br-lab.10   br-lab.20   br-lab.30          <- gateways .1, dnsmasq per subnet
                          |
            nftables inet labfw (forward/input)      <- lab/nftables/vlan-policy.nft
```
