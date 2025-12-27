# Multi-Agent Traffic Flow Coordination with VDN

This component implements a Multi-Agent Reinforcement Learning (MARL) system using the Value Decomposition Network (VDN) framework to enable coordinated traffic signal control across multiple intersections. By allowing traffic lights to communicate and collaborate, this system reduces city-wide congestion and creates adaptive traffic flow optimization.


## 🚦 Project Overview
Traditional traffic systems operate in isolation, where each intersection makes decisions based only on local information. This leads to sub-optimal global performance and propagating congestion waves throughout the city network.

This component solves this problem by implementing a Centralized Training with Decentralized Execution (CTDE) paradigm, where:

➡️During training, agents learn to cooperate by sharing a global reward signal

➡️During execution, each intersection operates independently using only local observations and lightweight neighbor communication

➡️The Value Decomposition Network (VDN) architecture enables agents to learn how their individual actions contribute to overall city-wide traffic optimization


## 🧠 WORKFLOW 

Simply put; the whole workflow for this component begins in two main phases.

### 1. Centralized Training Phase:

✔️ Agents interact with SUMO, taking actions based on local state.

✔️ Experiences (state, action, reward, next state) are stored in a shared replay buffer.

✔️ A central trainer (VDN mixer network) samples batches and updates all agent networks using the global reward signal.

![alt text](images/23.png)
### 2. Decentralized Execution Phase:

✔️ Trained agents are deployed.

✔️ Each agent uses its local observation (from SUMO via TraCI) and lightweight messages from neighbors.

✔️ It feeds this into its own neural network to choose the best action independently.

✔️ The action is executed in SUMO via TraCI.

![alt text](images/26.png)

### 3. Key Components:

![alt text](images/KEYcompo.png)

### 4. Tools & Technoologies used:

<p align="left">
  <!-- SUMO / TraCI -->
  <img src="https://img.shields.io/badge/SUMO-Traffic_Simulator-blue?style=flat-square"/>
  <img src="https://img.shields.io/badge/TraCI-API-lightgrey?style=flat-square"/>

  <!-- Python -->
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" width="40"/>

  <!-- PyTorch -->
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytorch/pytorch-original.svg" width="40"/>

  <!-- Neural Networks (AI generic icon) -->
  <img src="https://img.shields.io/badge/Neural_Networks-AI-red?style=flat-square"/>

  <!-- React -->
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/react/react-original.svg" width="40"/>

  <!-- Sockets -->
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/socketio/socketio-original.svg" width="40"/>
</p>
 

### 5. Dated Merges:
 Merge #4 - created basic project structure

 Merge #5 - Initialized SUMO configs and env wrapper

 Merge #6 - Created DQN Agent

 Merge #7 - Created VDN mixing network

 Merge #8 - Created Multi-Agent System

 Merge #9 - Created Main Training Loop

 Merge #10 - Created Evaluation Script

 Merge #11 - 

 Merge #12 - 

 Merge #13 - 

 Merge #14 - 

 Merge #15 - 

 Merge #16 - 

 Merge #17 - 

 Merge #18 - 

 Merge #19 - 

 Merge #20 - 

 Merge #21 - 

 Merge #22 - 

 Merge #23 - 

 Merge #24 - 

 Merge #25 - 
 
 


### 6. Setup:
1. mkdir traffic-marl-vdn -> cd traffic-marl-vdn
2. Created Virtual Environment
    python -m venv venv -> venv\Scripts\activate
3. Installed Core Dependencies
    pip install torch numpy pandas matplotlib
    pip install sumolib traci
    pip install pyzmq
4. Created Initial Project Structure
    mkdir configs
    mkdir agents
    mkdir utils
    mkdir sumo_configs
    mkdir logs
    mkdir models
    New-Item main.py
    New-Item requirements.txt
5. Setup SUMO configurations and 1x2 network in sumo_configs
6. Initialized SUMO environment wrapper in sumo_env.py
7. Created DQN Agent -> dqn_agent.py
8. Created VDN mixing network -> vdn_mixer.py
9. Created Multi-Agent System -> multi_agent_system.py
10. Created Main Training Loop -> main.py
11. Created Evaluation Script -> test.py



