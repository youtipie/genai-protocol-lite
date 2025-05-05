import multiprocessing
import subprocess


def run_test(file_name, arg1):
    """Run a test file with arguments"""
    subprocess.run(["python", file_name, str(arg1)])


def spawn_processes_for_all_files(file_names, num_processes=10000):
    """Spawns processes for multiple files at the same time"""
    processes = []

    # Start 10,000 processes for each test file simultaneously
    for file_name in file_names:
        for i in range(num_processes):
            process = multiprocessing.Process(target=run_test, args=(file_name, f"{i}"))
            process.start()
            processes.append(process)

    # Wait for all processes to complete
    for process in processes:
        process.join()


if __name__ == "__main__":
    test_files = ["agents.py", "clients.py"]
    spawn_processes_for_all_files(test_files, num_processes=1000)

    print("All processes completed.")
