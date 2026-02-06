import os

# Prevent tests from ever sending real iMessages
os.environ['FLOWERS_TESTING'] = '1'
