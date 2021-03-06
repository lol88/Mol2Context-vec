from rdkit import Chem
import torch
import torch.nn as nn
from sklearn import metrics
from sklearn.metrics import precision_recall_curve
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
import torch.nn.functional as F
import torch.utils.data as data
import pandas as pd
from sklearn.externals import joblib
# from paper_data.plot_morgan import main
import numpy as np
import seaborn as sns
import math
import random
from torch.autograd import Variable
import matplotlib.pyplot as plt
from scipy.stats import pearsonr
from sklearn.model_selection import KFold
from sklearn.metrics import mean_squared_error, mean_absolute_error

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def get_len(smi):
    mol = Chem.MolFromSmiles(smi)
    smiles = Chem.MolToSmiles(mol)
    mol = Chem.MolFromSmiles(smiles)
    mol_atoms = [a.GetIdx() for a in mol.GetAtoms()]
    return len(mol_atoms)

def pack_sequences(X, order=None):
    lengths = np.array([x.shape[0] for x in X])
    features = X[0].shape[1]
    n = len(X)
    if order is None:
        order = np.argsort(lengths)[::-1]  # 从后向前取反向的元素
    m = max(lengths)

    X_block = X[0].new(n, m, features).zero_()

    for i in range(n):
        j = order[i]
        x = X[j]
        X_block[i, :len(x), :] = x

    return X_block, order


def unpack_sequences(X, order):
    X, lengths = pad_packed_sequence(X, batch_first=True)
    X_block = torch.zeros(size=X.size()).to(device)
    for i in range(len(order)):
        j = order[i]
        X_block[j] = X[i]
    return X_block

def split_data(x, y, all_smi, k_fold):
    y = np.array(y, dtype=np.float64)
    # save_path = 'bace2/'+str(k_fold)+'-fold-index.pkl'
    # if os.path.isfile(save_path):
    #     index = joblib.load(save_path)
    #     train_split_x = x[index["train_index"]]
    #     train_split_y = y[index["train_index"]]
    #     val_split_x = x[index["val_index"]]
    #     val_split_y = y[index["val_index"]]
    #     test_split_x = x[index["test_index"]]
    #     test_split_y = y[index["test_index"]]
    #     train_weights = joblib.load('bace2/train_weights.pkl')
    #     return train_split_x, train_split_y, val_split_x, val_split_y, test_split_x, test_split_y, train_weights

    kf = KFold(5, True, 100)
    train_index = [[],[],[],[],[]]
    val_index = [[],[],[],[],[]]
    test_index = [[],[],[],[],[]]
    for k, tmp in enumerate(kf.split(x)):
        # train_tmp is  the index ofnegative_index
        train_tmp, test_tmp = tmp
        train_index[k].extend(train_tmp)
        num_t = int(len(test_tmp)/2)
        val_index[k].extend(test_tmp[0:num_t])
        test_index[k].extend(test_tmp[num_t:])


    for i in range(5):
        joblib.dump({"train_index":train_index[i],
                     "val_index": val_index[i],
                     "test_index": test_index[i],
                     }, 'lipop/'+str(i+1)+'-fold-index.pkl')
    train_split_x = x[train_index[k_fold]]
    train_split_y = y[train_index[k_fold]]
    train_split_smi = all_smi[train_index[k_fold]]
    val_split_x = x[val_index[k_fold]]
    val_split_y = y[val_index[k_fold]]
    val_split_smi = all_smi[val_index[k_fold]]
    test_split_x = x[test_index[k_fold]]
    test_split_y = y[test_index[k_fold]]
    test_split_smi = all_smi[test_index[k_fold]]
    return train_split_x, train_split_y, train_split_smi,\
           val_split_x, val_split_y, val_split_smi,\
           test_split_x, test_split_y, test_split_smi

class LSTM(nn.Module):
    """搭建rnn网络"""
    def __init__(self):
        super(LSTM, self).__init__()
        self.matrix = nn.Parameter(torch.tensor([0.33, 0.33, 0.33]), requires_grad=True)
        self.fc = nn.Linear(600, 1024)
        self.lstm = nn.LSTM(
            input_size=1024,
            hidden_size=1024,
            num_layers=2,
            dropout=0.3,
            batch_first=True)
        # self.fc1 = nn.Linear(512, 1024)
        # self.fc2 = nn.Linear(128, 1024)
        self.fc3 = nn.Linear(1024, 512)
        self.fc4 = nn.Linear(512, 1)
        self.dropout = nn.Dropout(p=0.5)

        # self.matrix1 = Variable(torch.tensor(0.33), requires_grad=True)
        # self.matrix2 = Variable(torch.tensor(0.33), requires_grad=True)
        # self.matrix3 = Variable(torch.tensor(0.33), requires_grad=True)

        # self.att_encoder = SelfAttention(350, 1)
        # self.att_dense = nn.Linear(512)
        # self.output_layer = nn.Dense(1)
        # self.bn1 = nn.BatchNorm1d(1024)
        # self.bn2 = nn.BatchNorm1d(256)
        # self.bn3 = nn.BatchNorm1d(128)

    def attention_net(self, x, query, mask=None):
        d_k = query.size(-1)  # d_k为query的维度

        # query:[batch, seq_len, hidden_dim*2], x.t:[batch, hidden_dim*2, seq_len]
        #         print("query: ", query.shape, x.transpose(1, 2).shape)  # torch.Size([128, 38, 128]) torch.Size([128, 128, 38])
        # 打分机制 scores: [batch, seq_len, seq_len]
        scores = torch.matmul(query, x.transpose(1, 2)) / math.sqrt(d_k)
        #         print("score: ", scores.shape)  # torch.Size([128, 38, 38])

        # 对最后一个维度 归一化得分
        alpha_n = F.softmax(scores, dim=-1)
        #         print("alpha_n: ", alpha_n.shape)    # torch.Size([128, 38, 38])
        # 对权重化的x求和
        # [batch, seq_len, seq_len]·[batch,seq_len, hidden_dim*2] = [batch,seq_len,hidden_dim*2] -> [batch, hidden_dim*2]
        context = torch.matmul(alpha_n, x).sum(1)

        att = torch.matmul(x, context.unsqueeze(2))/ math.sqrt(d_k)
        att = torch.sigmoid(att.squeeze())
        return context, alpha_n, att

    def forward(self, x):
        # print(self.matrix1, self.matrix2, self.matrix3)
        # bs = len(x)
        # length = np.array([t.shape[0] for t in x])

        x = x.to(device)
        out = self.matrix[0] * x[:, 0, :, :] + self.matrix[1] * x[:, 1, :, :] + self.matrix[2] * x[:, 2, :, :]

        out = self.fc(out.to(device)).to(device)
        # changed_length1 = length[orderD]
        # x = pack_padded_sequence(x, changed_length1, batch_first=True)

        out,(h_n, c_n) = self.lstm(out.to(device))     #h_state是之前的隐层状态

        # query = self.dropout(out)
        # #
        # # 加入attention机制
        # attn_output, alpha_n, att = self.attention_net(out, query)

        alpha_n =0
        att =0
        # out,hidden = self.lstm(x.to(device))     #h_state是之前的隐层状态
        # out = torch.cat((h_n[-1, :, :], h_n[-2, :, :]), dim=-1)
        # out1 = unpack_sequences(rnn_out, orderD)
        # for i in range(bs):
        #     out1[i,length[i]:-1,:] = 0
        out = torch.mean(out, dim=1).squeeze()
        # out = out[:,-1,:]


        #进行全连接
        # out = self.fc1(out[:,-1,:])
        # out = F.leaky_relu(out)
        # out = F.dropout(out, p=0.3)
        # out = self.fc2(out)
        # out = F.leaky_relu(out)
        # out = F.dropout(out, p=0.3)
        out = self.fc3(out)
        out = F.leaky_relu(out)
        out = self.dropout(out)
        out = self.fc4(out)
        # return F.softmax(out,dim=-1)
        return out, alpha_n, att

class MyDataset(data.Dataset):
    def __init__(self, compound, y, smi):
        super(MyDataset, self).__init__()
        self.compound = compound
        # self.compound = torch.FloatTensor(compound)
        # self.y = torch.FloatTensor(y)
        self.y = y
        self.smi = smi

    def __getitem__(self, item):
        return self.compound[item], self.y[item], self.smi[item]


    def __len__(self):
        return len(self.compound)

if __name__ == '__main__':
    # 设置超参数
    input_size = 512
    num_layers = 2  # 定义超参数rnn的层数，层数为1层
    hidden_size = 512  # 定义超参数rnn的循环神经元个数，个数为32个
    learning_rate = 0.01  # 定义超参数学习率
    epoch_num = 1000
    batch_size = 32
    best_loss = 10000
    test_best_loss = 1000
    weight_decay = 1e-5
    momentum = 0.9

    b = 0.051
    # filepath = "lipop/delaney.csv"
    # df = pd.read_csv(filepath, header=0, encoding="gbk")
    y = joblib.load('lipop/label.pkl')
    all_smi = np.array(joblib.load('lipop/smi.pkl'))

    x = joblib.load('lipop/lipop_embed.pkl')

    seed = 199
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    # 5-Fold
    train_split_x, train_split_y, train_split_smi, \
    val_split_x, val_split_y, val_split_smi, \
    test_split_x, test_split_y, test_split_smi = split_data(x, y, all_smi, 3)

    data_train = MyDataset(train_split_x, train_split_y, train_split_smi)
    dataset_train = data.DataLoader(dataset=data_train, batch_size=batch_size, shuffle=True)

    data_val = MyDataset(val_split_x, val_split_y, val_split_smi)
    dataset_val = data.DataLoader(dataset=data_val, batch_size=batch_size, shuffle=True)

    data_test = MyDataset(test_split_x, test_split_y, test_split_smi)
    dataset_test = data.DataLoader(dataset=data_test, batch_size=batch_size, shuffle=True)

    rnn = LSTM().to(device)


    #使用adam优化器进行优化，输入待优化参数rnn.parameters，优化学习率为learning_rate
    # optimizer = torch.optim.Adam(list(rnn.parameters())+[matrix1, matrix2, matrix3], lr=learning_rate)

    optimizer = torch.optim.SGD(rnn.parameters(),
                                lr=learning_rate, weight_decay = weight_decay,
                                momentum = momentum)
    loss_function = nn.MSELoss().to(device)

    # 按照以下的过程进行参数的训练
    for epoch in range(epoch_num):
        avg_loss = 0
        sum_loss = 0
        rnn.train()
        for index, tmp in enumerate(dataset_train):
            tmp_compound, tmp_y, tmp_smi = tmp
            optimizer.zero_grad()
            outputs, alpha_n, att_n = rnn(tmp_compound)
            # print(matrix1,matrix2,matrix3)
            # print(outputs.flatten())
            loss = loss_function(outputs.flatten(), tmp_y.type(torch.FloatTensor).to(device))

            # loss = (loss - b).abs() + b
            loss.backward()
            optimizer.step()

            sum_loss += loss
            # print("epoch:", epoch, "index: ", index,"loss:", loss.item())
        avg_loss = sum_loss / (index + 1)
        print("epoch:", epoch,"   train  "  "avg_loss:", avg_loss.item())
        # # 保存模型
        # if avg_loss < best_loss:
        #     best_loss = avg_loss
        #     PATH = 'lipop/lstm_net.pth'
        #     print("train save model")
        #     torch.save(rnn.state_dict(), PATH)

        # print(task_matrix[0], task_matrix[2], task_matrix[2])
        with torch.no_grad():
            rnn.eval()
            test_avg_loss = 0
            test_sum_loss = 0
            for index, tmp in enumerate(dataset_val):
                tmp_compound, tmp_y, tmp_smi = tmp

                outputs, alpha_n, att_n = rnn(tmp_compound)
                # print(outputs.flatten())
                loss = loss_function(outputs.flatten(), tmp_y.type(torch.FloatTensor).to(device))
                test_sum_loss += loss.item()


            test_avg_loss = test_sum_loss / (index + 1)
            print("epoch:", epoch,"   val  ", "avg_loss: ", test_avg_loss)
            # 保存模型
            if test_avg_loss < test_best_loss:
                test_best_loss = test_avg_loss
                print("test save model")
                torch.save(rnn.state_dict(), 'lipop/lstm_net.pth')
                att_flag = False
                # if test_avg_loss < 0.5:
                #     att_flag = True

                rnn.eval()
                test_avg_loss = 0
                test_sum_loss = 0
                all_pred = []
                all_label = []

                for index, tmp in enumerate(dataset_test):
                    tmp_compound, tmp_y, tmp_smi = tmp
                    loss = 0
                    outputs, alpha_n, att_n = rnn(tmp_compound)
                    # out_label = F.softmax(outputs, dim=1)
                    # pred = out_label.data.max(1, keepdim=True)[1].view(-1).cpu().numpy()
                    # pred_score = [x[tmp_y.cpu().detach().numpy()[i]] for i, x in enumerate(out_label.cpu().detach().numpy())]
                    # y_pred.extend(pred)
                    # y_pred_score.extend(pred_score)

                    if att_flag:
                        att = alpha_n.cpu().detach().numpy()
                        for att_i in range(alpha_n.shape[0]):
                            smi_len = get_len(tmp_smi[att_i])
                            if smi_len > 40:
                                continue
                            att_tmp = att[att_i,:smi_len*2,:smi_len*2]
                            att_heatmap = att_tmp[1::2, 1::2]
                            att_heatmap = (att_heatmap - att_heatmap.min()) / (att_heatmap.max() - att_heatmap.min())
                            # f, (ax1, ax2) = plt.subplots(figsize=(6, 6), nrows=1)
                            # if "O=C1NC(=O)C(N1)(c2ccccc2)c3ccccc3".__eq__(tmp_smi[att_i]):
                            #     joblib.dump(att_heatmap, 'lipop/att'+str(epoch)+'.pkl')
                            fig = sns.heatmap(att_heatmap, cmap='OrRd')
                            # plt.show()
                            scatter_fig = fig.get_figure()
                            try:
                                scatter_fig.savefig("lipop/att_img/"+str(tmp_smi[att_i])+".png", dpi=400)
                            except:
                                continue
                            finally:
                                plt.close()


                            att_word_tmp = att_n[att_i,:smi_len*2].cpu().detach().numpy()
                            att_word = att_word_tmp[1::2]
                            # if max(att_word) > 0.1:
                            a = []
                            for index,i in enumerate(att_word):
                                a.append(str(index)+",1,"+str(1-i)+","+str(1-i))
                            main(tmp_smi[att_i], a, [], "lipop/att_word/"+str(tmp_smi[att_i])+".png")



                    y_pred = outputs.to(device).view(-1)
                    y_label = tmp_y.float().to(device).view(-1)

                    all_label.extend(y_label.cpu().numpy())
                    all_pred.extend(y_pred.cpu().numpy())

                    # y_pred = torch.sigmoid(y_pred).view(-1)
                    # y_label = F.one_hot(y_label, 2).float().to(device)
                    loss += loss_function(y_pred, y_label)

                    test_sum_loss += loss.item()


                mse = mean_squared_error(all_label, all_pred)
                rmse = np.sqrt(mse)
                test_avg_loss = test_sum_loss / (index + 1)

                print("epoch:", epoch, "   test   avg_loss:", test_avg_loss
                      ," rmse : ", rmse)


