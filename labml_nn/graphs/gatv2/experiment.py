"""
---
title: Train a Graph Attention Network v2 (GATv2) on Cora dataset
summary: >
  This trains is a  Graph Attention Network v2 (GATv2) on Cora dataset
---

# Train a Graph Attention Network v2 (GATv2) on Cora dataset

[![View Run](https://img.shields.io/badge/labml-experiment-brightgreen)](https://app.labml.ai/run/8e27ad82ed2611ebabb691fb2028a868)
"""

from typing import Dict

import numpy as np
import torch
from torch import nn

from labml import lab, monit, tracker, experiment
from labml.configs import BaseConfigs
from labml.utils import download
from labml_helpers.device import DeviceConfigs
from labml_helpers.module import Module
from labml_nn.graphs.gatv2 import GraphAttentionV2Layer
from labml_nn.optimizers.configs import OptimizerConfigs


class CoraDataset:
    """
    ## [Cora Dataset](https://linqs.soe.ucsc.edu/data)

    Cora dataset is a dataset of research papers.
    For each paper we are given a binary feature vector that indicates the presence of words.
    Each paper is classified into one of 7 classes.
    The dataset also has the citation network.

    The papers are the nodes of the graph and the edges are the citations.

    The task is to classify the edges to the 7 classes with feature vectors and
    citation network as input.
    """
    # Labels for each node
    labels: torch.Tensor
    # Set of class names and an unique integer index
    classes: Dict[str, int]
    # Feature vectors for all nodes
    features: torch.Tensor
    # Adjacency matrix with the edge information.
    # `adj_mat[i][j]` is `True` if there is an edge from `i` to `j`.
    adj_mat: torch.Tensor

    @staticmethod
    def _download():
        """
        Download the dataset
        """
        if not (lab.get_data_path() / 'cora').exists():
            download.download_file('https://linqs-data.soe.ucsc.edu/public/lbc/cora.tgz',
                                   lab.get_data_path() / 'cora.tgz')
            download.extract_tar(lab.get_data_path() / 'cora.tgz', lab.get_data_path())

    def __init__(self, include_edges: bool = True):
        """
        Load the dataset
        """

        # Whether to include edges.
        # This is test how much accuracy is lost if we ignore the citation network.
        self.include_edges = include_edges

        # Download dataset
        self._download()

        # Read the paper ids, feature vectors, and labels
        with monit.section('Read content file'):
            content = np.genfromtxt(str(lab.get_data_path() / 'cora/cora.content'), dtype=np.dtype(str))
        # Load the citations, it's a list of pairs of integers.
        with monit.section('Read citations file'):
            citations = np.genfromtxt(str(lab.get_data_path() / 'cora/cora.cites'), dtype=np.int32)

        # Get the feature vectors
        features = torch.tensor(np.array(content[:, 1:-1], dtype=np.float32))
        # Normalize the feature vectors
        self.features = features / features.sum(dim=1, keepdim=True)

        # Get the class names and assign an unique integer to each of them
        self.classes = {s: i for i, s in enumerate(set(content[:, -1]))}
        # Get the labels as those integers
        self.labels = torch.tensor([self.classes[i] for i in content[:, -1]], dtype=torch.long)

        # Get the paper ids
        paper_ids = np.array(content[:, 0], dtype=np.int32)
        # Map of paper id to index
        ids_to_idx = {id_: i for i, id_ in enumerate(paper_ids)}

        # Empty adjacency matrix - an identity matrix
        self.adj_mat = torch.eye(len(self.labels), dtype=torch.bool)

        # Mark the citations in the adjacency matrix
        if self.include_edges:
            for e in citations:
                # The pair of paper indexes
                e1, e2 = ids_to_idx[e[0]], ids_to_idx[e[1]]
                # We build a symmetrical graph, where if paper $i$ referenced
                # paper $j$ we place an adge from $i$ to $j$ as well as an edge
                # from $j$ to $i$.
                self.adj_mat[e1][e2] = True
                self.adj_mat[e2][e1] = True


class GATv2(Module):
    """
    ## Graph Attention Network v2 (GATv2)

    This graph attention network has two [graph attention layers](index.html).
    """

    def __init__(self, in_features: int, n_hidden: int, n_classes: int, n_heads: int, dropout: float, share_weights: bool = True):
        """
        * `in_features` is the number of features per node
        * `n_hidden` is the number of features in the first graph attention layer
        * `n_classes` is the number of classes
        * `n_heads` is the number of heads in the graph attention layers
        * `dropout` is the dropout probability
        * `share_weights` if set to True, the same matrix will be applied to the source and the target node of every edge
        """
        super().__init__()

        # First graph attention layer where we concatenate the heads
        self.layer1 = GraphAttentionV2Layer(in_features, n_hidden, n_heads, is_concat=True, dropout=dropout, share_weights=share_weights)
        # Activation function after first graph attention layer
        self.activation = nn.ELU()
        # Final graph attention layer where we average the heads
        self.output = GraphAttentionV2Layer(n_hidden, n_classes, 1, is_concat=False, dropout=dropout, share_weights=share_weights)
        # Dropout
        self.dropout = nn.Dropout(dropout)

    def __call__(self, x: torch.Tensor, adj_mat: torch.Tensor):
        """
        * `x` is the features vectors of shape `[n_nodes, in_features]`
        * `adj_mat` is the adjacency matrix of the form
         `[n_nodes, n_nodes, n_heads]` or `[n_nodes, n_nodes, 1]`
        """
        # Apply dropout to the input
        x = self.dropout(x)
        # First graph attention layer
        x = self.layer1(x, adj_mat)
        # Activation function
        x = self.activation(x)
        # Dropout
        x = self.dropout(x)
        # Output layer (without activation) for logits
        return self.output(x, adj_mat)


def accuracy(output: torch.Tensor, labels: torch.Tensor):
    """
    A simple function to calculate the accuracy
    """
    return output.argmax(dim=-1).eq(labels).sum().item() / len(labels)


class Configs(BaseConfigs):
    """
    ## Configurations
    """

    # Model
    model: GATv2
    # Number of nodes to train on
    training_samples: int = 500
    # Number of features per node in the input
    in_features: int
    # Number of features in the first graph attention layer
    n_hidden: int = 64
    # Number of heads
    n_heads: int = 8
    # Number of classes for classification
    n_classes: int
    # Dropout probability
    dropout: float = 0.6
    # Whether to include the citation network
    include_edges: bool = True
    # Dataset
    dataset: CoraDataset
    # Number of training iterations
    epochs: int = 1_000
    # Loss function
    loss_func = nn.CrossEntropyLoss()
    # Device to train on
    #
    # This creates configs for device, so that
    # we can change the device by passing a config value
    device: torch.device = DeviceConfigs()
    # Optimizer
    optimizer: torch.optim.Adam

    def initialize(self):
        """
        Initialize
        """
        # Create the dataset
        self.dataset = CoraDataset(self.include_edges)
        # Get the number of classes
        self.n_classes = len(self.dataset.classes)
        # Number of features in the input
        self.in_features = self.dataset.features.shape[1]
        # Create the model
        self.model = GATv2(self.in_features, self.n_hidden, self.n_classes, self.n_heads, self.dropout)
        # Move the model to the device
        self.model.to(self.device)
        # Configurable optimizer, so that we can set the configurations
        # such as learning rate by passing the dictionary later.
        optimizer_conf = OptimizerConfigs()
        optimizer_conf.parameters = self.model.parameters()
        self.optimizer = optimizer_conf

    def run(self):
        """
        ### Training loop

        We do full batch training since the dataset is small.
        If we were to sample and train we will have to sample a set of
        nodes for each training step along with the edges that span
        across those selected nodes.
        """
        # Move the feature vectors to the device
        features = self.dataset.features.to(self.device)
        # Move the labels to the device
        labels = self.dataset.labels.to(self.device)
        # Move the adjacency matrix to the device
        edges_adj = self.dataset.adj_mat.to(self.device)
        # Add an empty third dimension for the heads
        edges_adj = edges_adj.unsqueeze(-1)

        # Random indexes
        idx_rand = torch.randperm(len(labels))
        # Nodes for training
        idx_train = idx_rand[:self.training_samples]
        # Nodes for validation
        idx_valid = idx_rand[self.training_samples:]

        # Training loop
        for epoch in monit.loop(self.epochs):
            # Set the model to training mode
            self.model.train()
            # Make all the gradients zero
            self.optimizer.zero_grad()
            # Evaluate the model
            output = self.model(features, edges_adj)
            # Get the loss for training nodes
            loss = self.loss_func(output[idx_train], labels[idx_train])
            # Calculate gradients
            loss.backward()
            # Take optimization step
            self.optimizer.step()
            # Log the loss
            tracker.add('loss.train', loss)
            # Log the accuracy
            tracker.add('accuracy.train', accuracy(output[idx_train], labels[idx_train]))

            # Set mode to evaluation mode for validation
            self.model.eval()

            # No need to compute gradients
            with torch.no_grad():
                # Evaluate the model again
                output = self.model(features, edges_adj)
                # Calculate the loss for validation nodes
                loss = self.loss_func(output[idx_valid], labels[idx_valid])
                # Log the loss
                tracker.add('loss.valid', loss)
                # Log the accuracy
                tracker.add('accuracy.valid', accuracy(output[idx_valid], labels[idx_valid]))

            # Save logs
            tracker.save()


def main():
    # Create configurations
    conf = Configs()
    # Create an experiment
    experiment.create(name='gatv2')
    # Calculate configurations.
    experiment.configs(conf, {
        # Adam optimizer
        'optimizer.optimizer': 'Adam',
        'optimizer.learning_rate': 5e-3,
        'optimizer.weight_decay': 5e-4,
    })
    # Initialize
    conf.initialize()

    # Start and watch the experiment
    with experiment.start():
        # Run the training
        conf.run()


#
if __name__ == '__main__':
    main()
