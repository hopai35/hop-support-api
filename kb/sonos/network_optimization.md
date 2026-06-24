# Sonos - Network Optimization

## Router Settings for Sonos

### Recommended Router Settings
- **WiFi Band**: Use 2.4GHz for best range (Sonos devices work on 2.4GHz only for older models; newer models support 5GHz).
- **Multicast**: Enable IGMP Snooping if available. Sonos uses multicast for group playback and alarms.
- **Channel**: Set 2.4GHz channel to 1, 6, or 11 (non-overlapping). Use a WiFi analyzer app to find the least congested channel.

### "Product Missing" Error
The #1 cause of this error is network configuration:

1. **Reboot your router** - unplug for 30 seconds, then plug back in.
2. **Reboot your Sonos system** - go to Settings > System > Network > Remove & Reboot.
3. **Check WiFi band** - If you have a mesh network, ensure Sonos is on the same node.
4. **Check router settings** - Disable "Client Isolation" or "AP Isolation" in your router settings.

### SonosNet (Sonos Wireless Mesh)
- Sonos devices can create their own mesh network called SonosNet.
- To enable: connect one Sonos device to your router via Ethernet.
- SonosNet uses a dedicated channel (default: 11) separate from your WiFi.

## Improving Multi-Room Performance
- Use wired connections for devices near your router.
- Keep Sonos devices at least 3 feet apart for optimal wireless mesh.
- Avoid placing Sonos devices near metal objects or large appliances.