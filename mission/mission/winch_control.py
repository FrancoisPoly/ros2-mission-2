#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Imu
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
import subprocess
import time, math
import threading
import struct

# Configuration
DEVICE = "/dev/ttyUSB0"  # Change this to your actual device
CAN_SPEED = 500000       # 500kbps
BAUDRATE = 2000000       # 2Mbps
MOTOR_ID = 1             # Motor ID

class WinchNode(Node):
    def __init__(self):
        super().__init__("Winch_Node")

        qos_profile = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,  # Ensures message delivery
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10
        )

        self.subscriber_ = self.create_subscription(String, '/go_winch', self.go_callback, qos_profile)

        qos_profile = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,  # Ensures message delivery
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10
        )

        self.subscriber_ = self.create_subscription(Imu, '/mavros/imu/data', self.v_accel, qos_profile)
        self.get_logger().info("Winch Subsriber started")

        self.motor_state = {
            "running": False,
            "direction": "none",  # "up", "down", or "none"
            "last_command_time": 0
        }


    def go_up(self):
        """Optimized for faster response"""
        # Skip full status check for faster response
        # Just send the commands directly
        
        # If we know we need to change direction, send stop
        if hasattr(self, 'motor_state') and self.motor_state.get("direction") == "down":
            self.control_motor("stop")
            time.sleep(0.1)  # Shorter wait
        
        # Batch commands instead of separate calls
        batch_commands = [
            # Format: (command_hex, description)
            (f"94 {self._float_to_hex(20.0)} {self._duration_to_hex(2.0)}", "Speed 20 RPM for 2s"),
            ("91 00 00 00 00 00 00 00", "Start Motor")
        ]
        self.send_batch_commands(batch_commands)
        
        # Update state without checking status
        self.motor_state = {
            "running": True,
            "direction": "up",
            "speed": 20,
            "last_command_time": time.time()
        }
        
        # Schedule stop with timer as before
        if hasattr(self, '_stop_timer') and self._stop_timer:
            self._stop_timer.cancel()
        
        self._stop_timer = threading.Timer(2.0, lambda: self.control_motor("stop"))
        self._stop_timer.start()

    def go_down(self):
        """Optimized for faster response"""
        # Skip full status check for faster response
        # Just send the commands directly
        
        # If we know we need to change direction, send stop
        if hasattr(self, 'motor_state') and self.motor_state.get("direction") == "up":
            self.control_motor("stop")
            time.sleep(0.1)  # Shorter wait
        
        # Batch commands instead of separate calls
        batch_commands = [
            # Format: (command_hex, description)
            (f"94 {self._float_to_hex(-20.0)} {self._duration_to_hex(2.0)}", "Speed -20 RPM for 2s"),
            ("91 00 00 00 00 00 00 00", "Start Motor")
        ]
        self.send_batch_commands(batch_commands)
        
        # Update state without checking status
        self.motor_state = {
            "running": True,
            "direction": "down",
            "speed": -20,
            "last_command_time": time.time()
        }
        
        # Schedule stop with timer as before
        if hasattr(self, '_stop_timer') and self._stop_timer:
            self._stop_timer.cancel()
        
        self._stop_timer = threading.Timer(2.0, lambda: self.control_motor("stop"))
        self._stop_timer.start()



    def go_callback(self, msg):
        self.get_logger().info(f"GO MESSAGE : {msg.data}")
        if msg.data == 'UP':
            self.go_up()
        if msg.data == 'DOWN':
            self.go_down()
    
    def v_accel(self, msg):
        self.get_logger().info(f"Vertical accel : {msg.linear_acceleration.z}")

    def control_motor(self, control_type, value=0.0, time_seconds=0.0, description=None):
        """
        General motor control function that handles different control types
        
        Args:
            control_type: String indicating the control type ("start", "stop", "speed", "position", "torque")
            value: Float value for speed (RPM), position (radians), or torque (N.m)
            time_seconds: Duration in seconds (not used for start/stop)
            description: Optional custom description for logging
        """
        
        
        # Convert time from seconds to milliseconds
        time_ms = int(time_seconds * 1000)
        time_bytes = struct.pack("<I", time_ms)[:3]  # Only need 3 bytes for 24-bit duration
        
        # Prepare command based on control type
        if control_type.lower() == "start":
            cmd_hex = "91 00 00 00 00 00 00 00"
            desc = description or "Start Motor"
        elif control_type.lower() == "stop":
            cmd_hex = "92 00 00 00 00 00 00 00"
            desc = description or "Stop Motor"
        elif control_type.lower() == "torque":
            # Convert torque value to IEEE float and format as hex
            value_bytes = struct.pack("<f", value)
            value_hex = " ".join([f"{b:02X}" for b in value_bytes])
            time_hex = " ".join([f"{b:02X}" for b in time_bytes]) + " 00"
            cmd_hex = f"93 {value_hex} {time_hex}"
            desc = description or f"Torque Control ({value} N.m for {time_seconds}s)"
        elif control_type.lower() == "speed":
            # Convert speed value to IEEE float and format as hex
            value_bytes = struct.pack("<f", value)
            value_hex = " ".join([f"{b:02X}" for b in value_bytes])
            time_hex = " ".join([f"{b:02X}" for b in time_bytes]) + " 00"
            cmd_hex = f"94 {value_hex} {time_hex}"
            desc = description or f"Speed Control ({value} RPM for {time_seconds}s)"
        elif control_type.lower() == "position":
            # Convert position value to IEEE float and format as hex
            value_bytes = struct.pack("<f", value)
            value_hex = " ".join([f"{b:02X}" for b in value_bytes])
            time_hex = " ".join([f"{b:02X}" for b in time_bytes]) + " 00"
            cmd_hex = f"95 {value_hex} {time_hex}"
            desc = description or f"Position Control ({value} rad for {time_seconds}s)"
        else:
            raise ValueError(f"Unsupported control type: {control_type}")
        
        # Send the command using the existing method
        return self.send_can_command(cmd_hex, desc)

    def read_indicator(self, indicator_id):
        """
        Read a specific motor indicator using Command 0xB4
        
        Args:
            indicator_id: Integer ID of the indicator to read (0x00-0x13)
            
        Returns:
            Float value of the requested indicator
        """
        import struct
        
        # Format the indicator ID as hex string
        ind_id_hex = f"{indicator_id:02X}"
        cmd_hex = f"B4 {ind_id_hex} 00 00 00 00 00 00"
        
        # Define indicator names for better logging
        indicator_names = {
            0x00: "Bus Voltage (V)",
            0x01: "Driver Board Temperature (°C)",
            0x02: "Motor Temperature (°C)",
            0x03: "Power (W)",
            0x04: "Phase Current Ia (A)",
            0x05: "Phase Current Ib (A)",
            0x06: "Phase Current Ic (A)",
            0x07: "Current Ialpha (A)",
            0x08: "Current Ibeta (A)",
            0x09: "Current Iq (A)",
            0x0A: "Current Id (A)",
            0x0B: "Target Current Iq (A)",
            0x0C: "Target Current Id (A)",
            0x0D: "Voltage Vq (V)",
            0x0E: "Voltage Vd (V)",
            0x0F: "Voltage Valpha (V)",
            0x10: "Voltage Vbeta (V)",
            0x11: "Electrical Angle (rad)",
            0x12: "Mechanical Angle (rad)",
            0x13: "Gear Mechanical Angle (rad)"
        }
        
        desc = f"Read {indicator_names.get(indicator_id, f'Indicator 0x{ind_id_hex}')}"
        result = self.send_can_command(cmd_hex, desc)
        
        if result and result.stdout:
            # Parse the response to extract the float value
            # The response format should be something like:
            # "Received: xx xx xx xx xx xx xx xx"
            # where the last 4 bytes are the IEEE float value
            try:
                # Extract the bytes from the response
                response_parts = result.stdout.strip().split()
                if len(response_parts) >= 9 and response_parts[0] == "Received:":
                    # Extract the last 4 bytes (DATA0-DATA3)
                    data_bytes = bytes.fromhex(''.join(response_parts[5:9]))
                    # Convert to float (IEEE format, LSB byte order)
                    value = struct.unpack('<f', data_bytes)[0]
                    return value
            except Exception as e:
                print(f"Error parsing indicator response: {e}")
        
        return None

    def get_motor_status(self):
        """
        Get comprehensive motor status including voltage, current, speed, position
        
        Returns:
            Dictionary containing motor status parameters
        """
        status = {}
        
        # Essential motor status indicators
        indicators_to_read = [
            (0x00, "voltage"),           # Bus Voltage (V)
            (0x03, "power"),             # Power (W)
            (0x09, "current_q"),         # Current Iq (A) - Torque producing current
            (0x0A, "current_d"),         # Current Id (A) - Field producing current
            (0x12, "mechanical_angle"),  # Mechanical Angle (rad)
            (0x13, "gear_angle")         # Gear Mechanical Angle (rad)
        ]
        
        for ind_id, key in indicators_to_read:
            value = self.read_indicator(ind_id)
            if value is not None:
                status[key] = value
        
        # Calculate actual speed based on successive position readings
        if 'gear_angle' in status:
            prev_angle = getattr(self, '_prev_angle', None)
            prev_time = getattr(self, '_prev_time', None)
            
            current_time = time.time()
            if prev_angle is not None and prev_time is not None:
                # Calculate angular velocity (rad/s)
                time_diff = current_time - prev_time
                angle_diff = status['gear_angle'] - prev_angle
                
                # Handle angle wrap-around (assuming angle is within -π to π)
                if angle_diff > math.pi:
                    angle_diff -= 2 * math.pi
                elif angle_diff < -math.pi:
                    angle_diff += 2 * math.pi
                    
                # Convert to RPM
                angular_velocity_rpm = (angle_diff / time_diff) * (60 / (2 * math.pi))
                status['actual_speed'] = angular_velocity_rpm
            
            # Store for next calculation
            self._prev_angle = status['gear_angle']
            self._prev_time = current_time
        
        return status



    def send_can_command(self, command_hex, description):
        """Send a CAN command and print details"""
        print(f"\n--- Sending: {description} ---")
        print(f"Command (hex): {command_hex}")
        
        # Convert hex string to bytes for display
        bytes_array = bytearray.fromhex(command_hex)
        print(f"Bytes: {' '.join(f'0x{b:02X}' for b in bytes_array)}")
        
        # Build the canusb command
        cmd = [
            "./mission/mission/canusb",
            "-d", DEVICE,
            "-s", str(CAN_SPEED),
            "-b", str(BAUDRATE),
            "-i", f"{MOTOR_ID:x}",  # Motor ID in hex
            "-j", command_hex,
            "-n", "1",              # Send once
            "-m", "2"               # Fixed payload mode
        ]
        
        # Execute the command
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(f"Command executed: {' '.join(cmd)}")
            
            if result.stdout:
                print(f"Stdout: {result.stdout}")
            if result.stderr:
                print(f"Stderr: {result.stderr}")
                
            # Wait a bit for the command to be processed
            time.sleep(0.005)
            return result
        except Exception as e:
            print(f"Error executing command: {e}")
            return None
    def _float_to_hex(self, value):
        """Convert float to hex string in correct format"""
        value_bytes = struct.pack("<f", value)
        return " ".join([f"{b:02X}" for b in value_bytes])

    def _duration_to_hex(self, seconds):
        """Convert seconds to duration hex string"""
        ms = int(seconds * 1000)
        time_bytes = struct.pack("<I", ms)[:3]
        return " ".join([f"{b:02X}" for b in time_bytes]) + " 00"

    def send_batch_commands(self, commands):
        """Send multiple commands with a single process invocation"""
        # Join commands with semicolons for the canusb program
        joined_commands = ";".join([cmd[0] for cmd in commands])
        description = " + ".join([cmd[1] for cmd in commands])
        
        print(f"\n--- Sending batch: {description} ---")
        print(f"Commands: {joined_commands}")
        
        # Build the command for multiple messages
        cmd = [
            "./mission/mission/canusb",
            "-d", DEVICE,
            "-s", str(CAN_SPEED),
            "-b", str(BAUDRATE),
            "-i", f"{MOTOR_ID:x}",
            "-j", joined_commands,
            "-n", "1",
            "-m", "2"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout:
                print(f"Stdout: {result.stdout}")
            if result.stderr:
                print(f"Stderr: {result.stderr}")
            return result
        except Exception as e:
            print(f"Error executing batch command: {e}")
            return None


def main(args=None):
    rclpy.init(args=args)
    node = WinchNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()