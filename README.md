# messenger-plus-to-gpt
Converts MSN Messenger Plus HTML log files to preprocessed JSON files for AI training

# Preparation
- Create a `data` folder with a `raw_data` and a `preprocessed` subfolders 
- Copy all your logs into `data/raw_data` (as HTML files)
- Install `beautifulsoup4` with pip

Then run :

```
python3 preprocess_msn.py "your@mail.com"
```

Replace `your@mail.com` with the e-mail address corresponding to your identity in those logs.

The output is meant to be used with https://github.com/LatentMindAI/perzonalized-ai-chatbot
