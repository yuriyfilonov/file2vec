import numpy as np
import time
import os

import theano
import theano.tensor as T

import parameters
import log
import validation
import kit
import binary


floatX = theano.config.floatX
empty = lambda *shape: np.empty(shape, dtype='int32')
rnd2 = lambda d0, d1: np.random.rand(d0, d1).astype(dtype=floatX)
asfx = lambda x: np.asarray(x, dtype=floatX)


class Model:
    def __init__(self, fileEmbeddings, wordEmbeddings, weights=None, contextSize=None, negative=None):
        filesCount, fileEmbeddingSize = fileEmbeddings.shape
        wordsCount, wordEmbeddingSize = wordEmbeddings.shape

        if weights is not None:
            featuresCount, activationsCount = weights.shape
            contextSize = (featuresCount - fileEmbeddingSize) / wordEmbeddingSize
            negative = activationsCount - 1
        else:
            weights = rnd2(fileEmbeddingSize + contextSize * wordEmbeddingSize, wordsCount)

        self.fileEmbeddings = theano.shared(asfx(fileEmbeddings), 'fileEmbeddings', borrow=True)
        self.wordEmbeddings = theano.shared(asfx(wordEmbeddings), 'wordEmbeddings', borrow=True)
        self.weights = theano.shared(asfx(weights), 'weights', borrow=True)

        fileIndexOffset = 0
        wordIndicesOffset = fileIndexOffset + 1
        indicesOffset = wordIndicesOffset + contextSize

        contexts = T.imatrix('contexts')
        context = T.flatten(contexts)
        fileIndex = context[fileIndexOffset:wordIndicesOffset]
        wordIndices = context[wordIndicesOffset:indicesOffset]
        indices = context[indicesOffset:indicesOffset + negative]

        file = self.fileEmbeddings[fileIndex]
        fileFeatures = T.flatten(file, outdim=1)
        words = self.wordEmbeddings[wordIndices]
        wordFeatures = T.flatten(words, outdim=1)
        features = T.concatenate([fileFeatures, wordFeatures], axis=0)

        subWeights = self.weights[:,indices]

        probabilities = T.dot(features, subWeights)

        parameters = [self.fileEmbeddings]
        subParameters = [file]
        consider_constant = [self.wordEmbeddings]

        if weights is not None:
            consider_constant.append(self.weights)
        else:
            parameters.append(self.weights)
            subParameters.append(subWeights)

        cost = -T.mean(T.log(T.nnet.sigmoid(probabilities[0])) + T.sum(T.log(T.nnet.sigmoid(-probabilities[1:]))))

        learningRate = T.scalar('learningRate', dtype=floatX)

        gradients = [T.grad(cost, wrt=subP, consider_constant=consider_constant) for subP in subParameters]
        updates = [(p, T.inc_subtensor(subP, -learningRate * g)) for p, subP, g in zip(parameters, subParameters, gradients)]

        contextIndex = T.iscalar('batchIndex')
        self.trainingContexts = theano.shared(empty(1,1), 'trainingContexts', borrow=True)

        self.trainModel = theano.function(
            inputs=[contextIndex, learningRate],
            outputs=cost,
            updates=updates,
            givens={
                contexts: self.trainingContexts[contextIndex:contextIndex + 1]
            }
        )


    def dump(self, fileEmbeddingsPath, weightsPath):
        fileEmbeddings = self.fileEmbeddings.get_value()
        binary.dumpMatrix(fileEmbeddingsPath, fileEmbeddings)

        weights = self.weights.get_value()
        binary.dumpMatrix(weightsPath, weights)


    @staticmethod
    def load(fileEmbeddingsPath, wordEmbeddingsPath, weightsPath):
        fileEmbeddings = binary.loadMatrix(fileEmbeddingsPath)
        wordEmbeddings = binary.loadMatrix(wordEmbeddingsPath)
        weights = binary.loadMatrix(weightsPath)

        return Model(fileEmbeddings, wordEmbeddings, weights)



def train(model, fileIndexMap, wordIndexMap, wordEmbeddings, contexts, metricsPath,
          epochs, batchSize, learningRate):
    model.trainingContexts.set_value(contexts)

    contextsCount, contextSize = contexts.shape

    startTime = time.time()
    for epoch in xrange(0, epochs):
        errors = []
        for contextIndex in xrange(0, contextsCount):
            error = model.trainModel(contextIndex, learningRate)
            errors.append(error)

        metrics = {
            'meanError': np.mean(errors),
            'medianError': np.median(errors),
            'maxError': np.max(errors),
            'minError': np.min(errors),
            'learningRate': learningRate
        }

        validation.dump(metricsPath, epoch, metrics)

        elapsed = time.time() - startTime

        log.progress('Training model: {0:.3f}%. Epoch: {1}. Elapsed: {2}. Error(mean,median,min,max): {3:.3f}, {4:.3f}, {5:.3f}, {6:.3f}. Learning rate: {7}.',
                     epoch + 1,
                     epochs,
                     epoch + 1,
                     log.delta(elapsed),
                     metrics['meanError'],
                     metrics['medianError'],
                     metrics['minError'],
                     metrics['maxError'],
                     learningRate)

    validation.compareEmbeddings(fileIndexMap, model.fileEmbeddings.get_value(), annotate=True)
    # validation.plotEmbeddings(fileIndexMap, model.fileEmbeddings.get_value())
    # validation.compareMetrics(metricsPath, 'error')


def launch(pathTo, hyper):
    fileIndexMap = parameters.loadIndexMap(pathTo.fileIndexMap)
    filesCount = len(fileIndexMap)
    fileEmbeddingSize = 800
    wordIndexMap = parameters.loadIndexMap(pathTo.wordIndexMap)
    wordEmbeddings = parameters.loadEmbeddings(pathTo.wordEmbeddings)
    metricsPath = pathTo.metrics('history.csv')

    if os.path.exists(metricsPath):
        os.remove(metricsPath)

    contextProvider = parameters.IndexContextProvider(pathTo.contexts)
    windowSize = contextProvider.windowSize - 1
    contextSize = windowSize - 1
    negative = contextProvider.negative
    contexts = contextProvider[:]

    log.info('Contexts loading complete. {0} contexts loaded {1} words and {2} negative samples each.',
             len(contexts),
             contextProvider.windowSize,
             contextProvider.negative)

    fileEmbeddings = rnd2(filesCount, fileEmbeddingSize)
    model = Model(fileEmbeddings, wordEmbeddings, contextSize=contextSize, negative=negative)
    # model = Model.load(pathTo.fileEmbeddings, pathTo.wordEmbeddings, pathTo.weights)

    train(model, fileIndexMap, wordIndexMap, wordEmbeddings, contexts, metricsPath,
          epochs=hyper.epochs,
          batchSize=hyper.batchSize,
          learningRate=hyper.learningRate)

    model.dump(pathTo.fileEmbeddings, pathTo.weights)


if __name__ == '__main__':
    pathTo = kit.PathTo('Duplicates', 'wiki_full_s800_w10_mc20_hs1.bin')
    hyper = parameters.HyperParameters(epochs=20, batchSize=1, learningRate=0.01)

    launch(pathTo, hyper)