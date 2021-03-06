from __future__ import print_function
import os
import sys
# Modify path for importing packages
paths = ['/home/hadoop/anaconda/bin',
 '/home/hadoop/anaconda/lib/python27.zip',
 '/home/hadoop/anaconda/lib/python2.7',
 '/home/hadoop/anaconda/lib/python2.7/plat-linux2',
 '/home/hadoop/anaconda/lib/python2.7/lib-tk',
 '/home/hadoop/anaconda/lib/python2.7/lib-old',
 '/home/hadoop/anaconda/lib/python2.7/lib-dynload',
 '/home/hadoop/anaconda/lib/python2.7/site-packages',
 '/home/hadoop/anaconda/lib/python2.7/site-packages/Sphinx-1.4.6-py2.7.egg',
 '/home/hadoop/anaconda/lib/python2.7/site-packages/setuptools-27.2.0-py2.7.egg']
sys.path = paths + sys.path

# Import packages for S3Logging Class
import boto3
import botocore
from io import StringIO, BytesIO
from datetime import datetime
import numpy as np
import pandas as pd

# Import packages for spark application
import pyspark as ps    # for the pyspark suite
from pyspark.sql.functions import udf, col
from pyspark.sql.types import ArrayType, StringType
import string
import unicodedata
from sklearn.feature_extraction.stop_words import ENGLISH_STOP_WORDS

import nltk
if '/home/hadoop/nltk_data' not in nltk.data.path:
    nltk.data.path.append('/home/hadoop/nltk_data')

from nltk.tokenize import sent_tokenize
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem.porter import PorterStemmer
from nltk.stem.snowball import SnowballStemmer
from nltk.util import ngrams
from nltk import pos_tag
from nltk import RegexpParser

from pyspark.ml.feature import CountVectorizer
from pyspark.ml.feature import IDF

from pyspark.ml.clustering import LDA


class S3Logging(object):
    """
    Object allowing for printing logs to an S3 file

    Useful for iteratively logging messsages in a long running script such as a
    Spark application where stdout is only available upon completion.

    NOTE: S3 does not allow appending to an already existing file and so your
    specified log will be rewritten upon each call to `push_log()`

    NOTE: Must have previously configured the awscli tools
    """
    def __init__(self, bucket, fname, tstamp=True, redirect_stderr=False, redirect_stdout=False, push=False, overwrite_existing=False):
        """
        Args:
            bucket (str): S3 Bucket name
            fname (str): Name to give to log file
            tstamp (bool): default True
                Whether to include a timestamp with each call to write
            redirect_stderr (bool): default False
                Direct all stderr messages to be logged
            redirect_stdout (bool): default False
                Direct all stdout messages to be logged
                NOTE: run `sys.stdout = sys.__stdout__` to restore default
                behavior
            push (bool): default False
                Copy log to S3 upon each call to write()
            overwrite_existing (bool): default False
                Whether to overwrite file if it already exists.  If False and
                the file does already exist, messages will be appended to the
                file
        """
        self._s3 = boto3.client('s3')
        self.bucket = bucket
        self.key = fname
        self._tstamp = tstamp
        self._push = push

        if redirect_stderr:
            # redirect all stderr outputs to write to self
            sys.stderr = self

        if redirect_stdout:
            # redirect all stdout outputs to write to self
            sys.stdout = self

        if not overwrite_existing and self._exists():
            body_obj = self._s3.get_object(Bucket=self.bucket, Key=self.key)['Body']
            # self._msg = str(body_obj.read(), 'utf-8')
            if sys.version_info.major < 3:
                self._msg = str(body_obj.read())
            else:
                self._msg = str(body_obj.read(), 'utf-8')
        else:
            self._msg = ''

    def write(self, msg, push=None):
        if push is None:
            push = self._push

        # Append message with or without timestamp
        if self._tstamp and bool(msg):
            self._msg += "\n{0}\n{1}\n".format(datetime.now(), msg)
        else:
            self._msg += "\n{0}\n".format(msg)

        if push:
            self.push_log()

    def push_log(self):
        if sys.version_info.major < 3:
            f_handle = StringIO(unicode(self._msg))
        else:
            f_handle = StringIO(self._msg)
        self._s3.put_object(Bucket=self.bucket, Key=self.key, Body=f_handle.read())

    def restore_stdout(self):
        sys.stdout = sys.__stdout__


    def _exists(self):
        bucket = boto3.resource('s3').Bucket(self.bucket)
        objs = list(bucket.objects.filter(Prefix=self.key))
        return len(objs) > 0 and objs[0].key == self.key

    def __repr__(self):
        return self._msg


def save_numpy_to_s3(bucket, fname, *args, **kwds):
    s3 = boto3.client('s3')
    temp = BytesIO()
    np.savez(temp, *args, **kwds)
    temp.seek(0)
    s3.put_object(Bucket=bucket, Key=fname, Body=temp.read())


def load_numpy_from_s3(bucket, fname):
    s3 = boto3.client('s3')
    body_obj = s3.get_object(Bucket=bucket, Key=fname)['Body']
    temp = BytesIO(body_obj.read())
    return np.load(temp)


def extract_bow_from_raw_text(text_as_string):
    """Extracts bag-of-words from a raw text string.

    Parameters
    ----------
    text (str): a text document given as a string

    Returns
    -------
    list : the list of the tokens extracted and filtered from the text
    """
    if (text_as_string == None):
        return []

    if (len(text_as_string) < 1):
        return []

    import nltk
    if '/home/hadoop/nltk_data' not in nltk.data.path:
        nltk.data.path.append('/home/hadoop/nltk_data')

    nfkd_form = unicodedata.normalize('NFKD', unicode(text_as_string))
    text_input = nfkd_form.encode('ASCII', 'ignore')

    sent_tokens = sent_tokenize(text_input)

    tokens = map(word_tokenize, sent_tokens)

    sent_tags = map(pos_tag, tokens)

    grammar = r"""
        SENT: {<(J|N).*>}                # chunk sequences of proper nouns
    """

    cp = RegexpParser(grammar)
    ret_tokens = list()
    stemmer_snowball = SnowballStemmer('english')

    for sent in sent_tags:
        tree = cp.parse(sent)
        for subtree in tree.subtrees():
            if subtree.label() == 'SENT':
                t_tokenlist = [tpos[0].lower() for tpos in subtree.leaves()]
                t_tokens_stemsnowball = map(stemmer_snowball.stem, t_tokenlist)
                #t_token = "-".join(t_tokens_stemsnowball)
                #ret_tokens.append(t_token)
                ret_tokens.extend(t_tokens_stemsnowball)
            #if subtree.label() == 'V2V': print(subtree)
    #tokens_lower = [map(string.lower, sent) for sent in tokens]

    stop_words = {'book', 'author', 'read', "'", 'character', ''}.union(ENGLISH_STOP_WORDS)

    tokens = [token for token in ret_tokens if token not in stop_words]

    return(tokens)


def indexing_pipeline(input_df, **kwargs):
    """ Runs a full text indexing pipeline on a collection of texts contained
    in a DataFrame.

    Parameters
    ----------
    input_df (DataFrame): a DataFrame that contains a field called 'text'

    Returns
    -------
    df : the same DataFrame with a column called 'features' for each document
    wordlist : the list of words in the vocabulary with their corresponding IDF
    """
    inputCol_ = kwargs.get("inputCol", "text")
    vocabSize_ = kwargs.get("vocabSize", 5000)
    minDF_ = kwargs.get("minDF", 2.0)

    tokenizer_udf = udf(extract_bow_from_raw_text, ArrayType(StringType()))
    df_tokens = input_df.withColumn("bow", tokenizer_udf(col(inputCol_)))

    cv = CountVectorizer(inputCol="bow", outputCol="vector_tf", vocabSize=vocabSize_, minDF=minDF_)
    cv_model = cv.fit(df_tokens)
    df_features_tf = cv_model.transform(df_tokens)

    idf = IDF(inputCol="vector_tf", outputCol="features")
    idfModel = idf.fit(df_features_tf)
    df_features = idfModel.transform(df_features_tf)

    return(df_features, cv_model.vocabulary)


if __name__=='__main__':
    # Create logging object for writing to S3
    log = S3Logging('spark-talk', 'application-log.txt', overwrite_existing=True, redirect_stdout=True)

    print("Starting execution...")
    log.push_log()

    # Get or Create a new SparkSession object
    spark = ps.sql.SparkSession.builder \
                .appName("Spark Talk") \
                .getOrCreate()

    ''' Previously ran to subset full dataset down to 5% of original '''
    # # Use SparkSession to read in json object into Spark DataFrame
    # url = "s3n://spark-talk/reviews_Books_5.json.gz"
    # reviews = spark.read.json(url)
    #
    # # Let's subset our DataFrame to keep 5% of the reviews
    # review_subset = reviews.select('reviewText', 'overall') \
    #                        .sample(False, 0.05, 42)
    #
    # # Save this subset file to S3
    # review_subset.write.save('s3n://spark-talk/reviews_Books_subset5.json',
    #                          format='json')

    url = 's3n://spark-talk/reviews_Books_subset5.json'
    review_subset = spark.read.json(url)

    count = review_subset.count()
    print("reviews_Books_subset5.json contains {} elements".format(count))
    log.push_log()

    print("First 10 rows of review_subset DataFrame...")
    review_subset.show(10, truncate=True)
    log.push_log()

    review_df, vocab = indexing_pipeline(review_subset, inputCol='reviewText')

    # Persist this DataFrame to keep it in memory
    review_df.persist()

    # print the top 5 elements of the DataFrame and schema to the log
    print(review_df.take(5))
    review_df.printSchema()
    log.push_log()

    print("Example of first 50 words in our Vocab:")
    print(vocab[:50])
    log.push_log()

    # Save vocab object to S3
    save_numpy_to_s3('spark-talk', 'vocab_array.npz', vocab=vocab)

    for num_topics in [5, 10, 20]:
        lda = LDA(k=num_topics, maxIter=10, seed=42, featuresCol='features')
        model = lda.fit(review_df)
        model_description = model.describeTopics(20)
        model_descrip_path = 's3n://spark-talk/lda_{}_model_description'.format(num_topics)

        # Let's save the model description
        model_description.write.save(model_descrip_path, format='json')
