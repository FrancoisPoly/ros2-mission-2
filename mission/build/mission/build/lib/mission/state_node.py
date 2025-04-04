#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
import helper_func as hf
import itertools
import numpy as np
import time

# Taken from https://medium.com/@davidlfliang/intro-python-algorithms-traveling-salesman-problem-ffa61f0bd47b
"""
Brute force approach to the tmp
"""


def func_distance(pos1: list[int], pos2: list[int]) -> float:
    """
    Function to find the distance between two points
    """
    if len(pos1) != len(pos2):
        raise TypeError("The two points must be of the same dimension")
    return np.linalg.norm(np.array(pos1) - np.array(pos2))


def calculate_cost(route: list[tuple], distances: dict) -> float:
    """
    Function to calculate the total cost of a route
    """
    total_cost = 0
    n = len(route)
    for i in range(n):
        current_point = route[i][0]
        next_point = route[(i + 1) % n][0]  # Wrap around to the start of the route
        # Look up the distance in both directions
        if (current_point, next_point) in distances:
            total_cost += distances[(current_point, next_point)]
        else:
            total_cost += distances[(next_point, current_point)]
    return total_cost


def tmp_solution(buckets: dict) -> list[tuple[str, list[int]]]:
    """
    Function that takes in a dict. (name: bucket postion) and outputs the optimal route to take
    """
    # Dict. that holds all distances
    distances = {}

    for i in range(len(buckets) - 1):
        for j in range(len(buckets)):
            if j <= i:
                pass
            else:
                distances[(buckets[i][0], buckets[j][0])] = func_distance(
                    buckets[i][1], buckets[j][1]
                )

    # Generate all permutations of the buckets
    all_permutations = itertools.permutations(buckets)

    # Initialize variables to track the minimum cost and corresponding route
    min_cost = float("inf")
    optimal_route = None

    # Iterate over all permutations and calculate costs
    for perm in all_permutations:
        cost = calculate_cost(perm, distances)
        if cost < min_cost:
            min_cost = cost
            optimal_route = perm

    answer = []
    for bucket in optimal_route:
        answer.append(bucket)

    # Return the optimal route
    return (answer, distances)


class StateNode(Node):
    def __init__(self, position_dict: dict):
        super().__init__("State_node")

        qos_profile = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )

        # Let's define the important points in space
        self.ground_station = ("ground station", [0, 0, 0])
        self.water_source = ("water source", [50, 50, 20])
        # Optimal route to go to all buckets with the Travelling Marchant Problem brute force solution
        self.position_dict = position_dict
        self.optimal_route, self.distances = tmp_solution(self.position_dict)

        self.publisher_ = self.create_publisher(String, "go_vision", qos_profile)
        self.msg = String()
        self.get_logger().info("✅ State node started and listening.")

        # MAVLink Connection
        self.mav = hf.pymav()
        self.mav.connect("udp:127.0.0.1:14551")
        self.mav.set_mode("GUIDED")

        # Information on the drone
        self.drone_battery = 100.0  # %
        self.drone_travel_efficiency = 2 # Distance units per % of battery

        # Starting the mission
        self.action()

    def action(self) -> None:
        # Scheduling a timer to call a function checking if there's an opportunity to come back to base to charge the battery
        self.timer_battery = self.create_timer(10.0, self.charge_opportunity)  # Checking every 10 sec.

        # Schedule takeoff using a timer instead of blocking the main thread
        self.timer_takeoff = self.create_timer(1.0, self.takeoff_callback)

        # Then destroying the takeoff timer and starting the vision node
        self.destroy_timer(self.timer_takeoff)
        self.start_vision()

        # Schedule moving to the water source using a timer instead of blocking the main thread
        self.timer_move = self.create_timer(
            2.0, self.move_callback(self.water_source[0][1], self.water_source[0][0])
        )
        # Starting the node to fill up the water tank
        self.start_filling_up()

        self.current_pos = self.water_source
        for _ in range(len(self.optimal_route)):
            # Making sure the drone can do the travel without running out of battery 
            if self.possible_movement(self.optimal_route[0]):
                # Schedule moving to the current bucket using a timer instead of blocking the main thread
                self.timer_move = self.create_timer(
                    2.0,
                    self.move_callback(self.optimal_route[0][1], self.optimal_route[0][0]),
                )
                # Updating the current position
                self.current_pos = self.optimal_route[0]
                # Starting the node to drop water
                self.start_dropping_water()
                # Removing the current bucket from the list
                self.optimal_route.pop(0)
            else:
                self.mav.RTL()
                break

        # If there are no buckets left to go to, return to base
        if len(self.optimal_route) == 0:
            self.mav.RTL()

    def takeoff_callback(self) -> None:
        """Takeoff command, scheduled to prevent blocking."""
        self.get_logger().info("🚀 Takeoff initiated...")
        self.mav.arm()
        self.mav.takeoff(20)

    def move_callback(self, pos_coordinates: list[int], pos_name: str = "") -> None:
        """Move to the target position."""
        self.get_logger().info(f"🎯 Moving to target location {pos_name} ...")
        self.mav.global_target(pos_coordinates)

        # Destroying the "travel" timer
        self.destroy_timer(self.timer_move)

    def start_vision(self) -> None:
        self.msg = String()
        self.msg.data = "GO"
        self.publisher_.publish(self.msg)
        self.get_logger().info(f"VISION GO")

    def start_filling_up(self) -> None:
        self.msg = String()
        self.msg.data = "REFILL"
        self.publisher_.publish(self.msg)
        self.get_logger().info(f"FILLING UP GO")

    def start_dropping_water(self) -> None:
        self.msg = String()
        self.msg.data = "RELEASE"
        self.publisher_.publish(self.msg)
        self.get_logger().info(f"DROPPING WATER GO")

    def charge_opportunity(self) -> None:
        # Drone's current position
        drone_position = self.mav.get_local_pos()
        # If the drone is close enough to the ground station and the battery is nearly dead, let's take the opportunity to recharge it
        if (
            self.mav.is_near_waypoint(drone_position, self.ground_station[1], 100) #is near waypoint marche mieux avec coordonnées locale
            and self.drone_battery <= 10
        ):
            # Returning to launch
            self.mav.RTL()
            print("Charging battery ... ")
            time.sleep(3)
            print("Battery is charged!")
            self.drone_battery = 100.0  # %
    
    def possible_movement(self, target_pos: tuple[str, list[int]]) -> bool:
        #TODO Do profilling to see if the try-except block is faster than re-calculating the distance 
        try:
            next_distance = self.distances[(self.current_pos[0], target_pos[0])]
        except:
            try:
                next_distance = self.distances[(self.current_pos[0], target_pos[0])]
            except:
                next_distance = func_distance(self.current_pos[1], target_pos[1]) # Possibly faster to do this in every cases

        # Distance from the target to the ground station
        distance_target_to_base = func_distance(target_pos[1], self.ground_station[1])

        # Approximate battery level and drone's autonomy when it will have met the target
        battery_at_target = self.drone_battery - (next_distance/self.drone_travel_efficiency)
        autonomy_at_target = battery_at_target*self.drone_travel_efficiency
        return autonomy_at_target > distance_target_to_base

# Define the buckets and their distances
# TODO Make it so this dict. is not hard coded. I believe this data would come from the first phase.
buckets = [
    ("bucket_1", [10, 0, 10]),
    ("bucket_2", [0, 10, 10]),
    ("bucket_3", [0, 5, 15]),
    ("bucket_4", [6, 0, 66]),
    ("bucket_5", [0, 40, 10]),
    ("bucket_6", [20, 30, 10]),
    ("bucket_7", [20, 234, 223]),
    ("bucket_8", [222, 10, 49]),
]


def main(args=None):
    rclpy.init(args=args)
    node = StateNode(buckets)
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
