import kagglehub
import pandas as pd

path = kagglehub.dataset_download("goyaladi/twitter-dataset")
print(path)  # shows where it was cached locally

df = pd.read_csv(path + "/twitter_dataset.csv")  # filename may differ, check path
print(df.columns.tolist())
print(df.head(2))
