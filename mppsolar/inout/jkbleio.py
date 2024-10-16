""" mppsolar / inout / jkbleio.py """
import logging

try:
    from bluepy import btle
except ImportError:
    print("You are missing dependencies in order to be able to use that output.")
    print("To install them, use that command:")
    print("    python -m pip install 'mppsolar[ble]'")

from .baseio import BaseIO
from ..helpers import get_kwargs
from .jkbledelegate import jkBleDelegate

log = logging.getLogger("JkBleIO")

BLE_MTU = 330
JK_SERVICE_UUID = "ffe0"
READ_CHARACTERISTIC_UUID = "ffe1" 

getInfo = (
        b"\xaa\x55\x90\xeb\x97\x00\x34\x2b\x08\xe6\xd2\x4e\x5e\x66\x65\x90\x11\x01\xa2\xeb",
        b"\xaa\x55\x90\xeb\x97\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x11",
)
# getInfo = b"\xaa\x55\x90\xeb\x97\x00\xdf\x52\x88\x67\x9d\x0a\x09\x6b\x9a\xf6\x70\x9a\x17\xfd"


class JkBleIO(BaseIO):
    def __init__(self, device_path) -> None:
        self._device = None
        self._device_path = device_path
        self.maxConnectionAttempts = 3
        self.record = None

    def send_and_receive(self, *args, **kwargs) -> dict:
        # Send the full command via the communications port
        command = get_kwargs(kwargs, "command")
        protocol = get_kwargs(kwargs, "protocol")
        full_command = protocol.get_full_command(command)
        log.info(f"full command {full_command} for command {command}")

        command_defn = protocol.get_command_defn(command)
        record_type = command_defn["record_type"]
        log.debug(f"expected record type {record_type} for command {command}")

        # Connect to BLE device
        if self.ble_connect(self._device_path, protocol, record_type):
            response = self.ble_get_data(full_command)
            self.ble_disconnect()
        else:
            log.error(f"Failed to connect to {self._device_path}")
            response = None
        # End of BLE device connection
        log.debug(f"Raw response {response}")
        return response

    def ble_connect(self, mac=None, protocol=None, record_type=0x02):
        """
        Connect to a BLE device with 'mac' address
        """
        self._device = btle.Peripheral()
        self._device.withDelegate(jkBleDelegate(self, protocol, record_type))
        log.info(f"Attempting to connect to {mac}")
        for attempt in range(self.maxConnectionAttempts):
            try:
                self._device.connect(mac)
                self._device.setMTU(BLE_MTU)
                return True
            except Exception as e:
                log.debug("Connection exception: %s" % e)
                continue
        else:
            log.warning(f"Cannot connect to mac {mac} - exceeded {self.maxConnectionAttempts} attempts")
            return False

    def ble_disconnect(self):
        log.info("Disconnecting BLE Device...")
        self._device.disconnect()
        self._device = None
        return

    def ble_get_data(self, command=None):
        self.record = None

        log.debug(f"Command: {command}")

        if command is None:
            return self.record

        # Connect to the notify service
        notification_service = self._device.getServiceByUUID(JK_SERVICE_UUID)
        notification_char = [n for n in notification_service.getCharacteristics() if n.properties & n.props['NOTIFY']][0]
        log.info("Notification characteristic: {}, handle {:x}".format(notification_char, notification_char.getHandle()))
        client_config_desc = notification_service.getDescriptors(btle.AssignedNumbers.clientCharacteristicConfiguration)[0]
        log.info("Client Config Descriptor: {}, handle {:x}".format(client_config_desc, client_config_desc.handle))

        log.info("Enable Client Characteristic Configuration handle")
        client_config_desc.write(b"\x01\x00", True)
        log.info("Enable read handle")
        notification_char.write(b"\x01\x00")
        log.info("Write getInfo to read handle")
        notification_char.write(getInfo[1])

        self._device.waitForNotifications(1.0)

        if command == b"getInfo":
            return self.record[:300]

        log.info(
            "Write command to read handle",
            self._device.writeCharacteristic(handleRead, command),
        )
        loops = 0
        recordsToGrab = 1
        log.info("Grabbing {} records (after inital response)".format(recordsToGrab))

        while True:
            loops += 1
            if loops > recordsToGrab * 15 + 16:
                log.info("jkbleio: ble_get_dataa: Got {} records".format(recordsToGrab))
                break
            if self._device.waitForNotifications(1.0):
                continue

        log.debug(f"Record now {self.record} len {len(self.record)}")
        return self.record[:300]
