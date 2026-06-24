# Framework - OS & Driver Support

## Supported Operating Systems
- Windows 11 (recommended)
- Windows 10
- Ubuntu 22.04 LTS and 24.04 LTS
- Fedora 38+
- Arch Linux

## Driver Installation

### Windows
1. Visit knowledgebase.frame.work/drivers and download the Driver Pack for your model.
2. Run the installer as Administrator.
3. For fresh installs, download the Framework WiFi driver separately and transfer via USB.

### Linux
- Most drivers are included in mainline kernels (5.19+ recommended).
- For AMD 7040 series: kernel 6.3+ recommended for full iGPU support.
- The `fw-ectool` utility (from GitHub) allows controlling expansion card power and fan curves.

## BIOS Updates
1. Download the BIOS update from knowledgebase.frame.work/bios.
2. Extract to a FAT32 USB drive.
3. Reboot and press F2 to enter BIOS setup, then select "Update BIOS" from the Advanced menu.
4. Do NOT power off during update.

## Common OS Issues

### Windows: Bluetooth not working
- Ensure the WiFi module drivers are installed (Bluetooth is integrated).
- Toggle Bluetooth off/on in Settings > Bluetooth & devices.
- Run the Bluetooth troubleshooter.

### Linux: WiFi dropping
- For Intel AX210 modules, install the latest `iwlwifi` firmware:
  `sudo apt install linux-firmware`
- Disable power saving: `sudo iwconfig wlan0 power off`