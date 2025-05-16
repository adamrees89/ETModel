
import pandas as pd
import yaml

def main():
    with open("config.yaml", "r") as file:
        config = yaml.safe_load(file)
    print("Loaded configuration:", config)

if __name__ == "__main__":
    main()
