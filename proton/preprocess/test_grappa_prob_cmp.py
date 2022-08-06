#coding=utf8
import os
import numpy as np
import torch
import stanza, torch
import torch.nn.functional as F
from itertools import product, combinations
from transformers import AutoModel, AutoConfig,AutoTokenizer
import matplotlib.pyplot as plt

def agg(input):
    return torch.sum(input,dim=1,keepdim=True)/input.size(1)

if __name__=='__main__':
    nlp = stanza.Pipeline('en', processors='tokenize,pos,lemma')#, use_gpu=False)
    device = torch.device("cuda:0")
    hidden_size=1024
    max_batch_size = 8
    plm_model = AutoModel.from_pretrained(os.path.join('./pretrained_models', 'grappa_large_jnt')).to(device)
    plm_tokenizer = AutoTokenizer.from_pretrained(os.path.join('./pretrained_models', 'grappa_large_jnt'))
    config = plm_model.config
    raw_question_toks=['list', 'the', 'most', 'common', 'result', 'of', 'the', 'musicals', '.']
    column_names=['*', 'musical id', 'name', 'year', 'award', 'category', 'nominee', 'result', 'actor id', 'name', 'musical id', 'character', 'duration', 'age']
    table_names=['musical', 'actor']
    question = " ".join(raw_question_toks)
    doc = nlp(question)
    raw_question_toks = [w.lemma.lower() for s in doc.sentences for w in s.words]
    
    q_num, t_num, c_num = len(raw_question_toks), len(table_names), len(column_names)
    t_q_dict = {}
    c_q_dict = {}
    max_len = max([len(t.split()) for t in table_names])
    index_pairs = list(filter(lambda x: x[1] - x[0] <= max_len, combinations(range(q_num + 1), 2)))
    index_pairs = sorted(index_pairs, key=lambda x: x[1] - x[0])
    for i, j in index_pairs:
        phrase = ' '.join(raw_question_toks[i: j])
        for idx, name in enumerate(table_names):
            if phrase == name:
                if idx in t_q_dict.keys():
                        t_q_dict[idx].append([phrase,i,j])
                else:
                    t_q_dict[idx]=[[phrase,i,j]]  
            elif (j - i == 1 and phrase in name.split()) or (j - i > 1 and phrase in name):
                if idx in t_q_dict.keys():
                        t_q_dict[idx].append([phrase,i,j])
                else:
                    t_q_dict[idx]=[[phrase,i,j]]  
    print(t_q_dict)

    print('Q', len(raw_question_toks), raw_question_toks)
    print('C', len(column_names), column_names)
    print('T', len(table_names), table_names)

    question_id = [plm_tokenizer.cls_token_id]
    question = [q.lower() for q in raw_question_toks]
    question_subword_len = []
    for w in question:
        toks = plm_tokenizer.convert_tokens_to_ids(plm_tokenizer.tokenize(w))
        question_id.extend(toks)
        question_subword_len.append(len(toks))
    question_mask_plm = [0] + [1] * (len(question_id) - 1) + [0]
    exact_question_token=len(question_id) - 1
    question_id.append(plm_tokenizer.sep_token_id)

    masked_question_id = [question_id]
    
    start=1
   
    for i,sub_len in enumerate(question_subword_len):
        tmp_question_id=question_id.copy()
        for m in range(start,start+sub_len):
            tmp_question_id[m]=plm_tokenizer.mask_token_id
        masked_question_id.append(tmp_question_id)
        start+=sub_len
       
    table = [t.lower().split() for t in table_names]
    table_id, table_mask_plm, table_subword_len = [], [], []
    table_word_len = []
    for s in table:
        l = 0
        for w in s:
            toks = plm_tokenizer.convert_tokens_to_ids(plm_tokenizer.tokenize(w))
            table_id.extend(toks)
            table_subword_len.append(len(toks))
            l += len(toks)
        table_word_len.append(l)
    table_mask_plm = [1] * len(table_id)

    column = [t.lower().split() for t in column_names]
    column_id, column_mask_plm, column_subword_len = [], [], []
    column_word_len = []
    for s in column:
        l = 0
        for w in s:
            toks = plm_tokenizer.convert_tokens_to_ids(plm_tokenizer.tokenize(w))
            column_id.extend(toks)
            column_subword_len.append(len(toks))
            l += len(toks)
        column_word_len.append(l)
    column_mask_plm = [1] * len(column_id) + [0]
    exact_column_token=len(column_id)
    column_id.append(plm_tokenizer.sep_token_id)

    question_mask_plm = question_mask_plm + [0] * (len(table_id) + len(column_id))
    table_mask_plm = [0] * len(question_id) + table_mask_plm + [0] * len(column_id)
    column_mask_plm = [0] * (len(question_id) + len(table_id)) + column_mask_plm
    
    input_id=[]
    segment_id=[]
    atten_mask=[]
    for i, msk_q_id in enumerate(masked_question_id):
        input_id.append(msk_q_id + table_id + column_id)
        segment_id.append([0] * len(msk_q_id) + [1] * (len(table_id) + len(column_id)))
        atten_mask.append([1]*len(input_id[-1]))

    start=0
    total_size=len(input_id)
    #print(total_size)
    store_arr=[]
    if total_size <= max_batch_size:
        ii=torch.tensor(input_id, dtype=torch.long, device=device)
        im=torch.tensor(atten_mask, dtype=torch.float, device=device)
        si=torch.tensor(segment_id, dtype=torch.long, device=device)
        outputs = plm_model(ii,im)[0].squeeze()
        store_arr.append(outputs)
    else:
        while start < len(input_id):
            if start + max_batch_size <= len(input_id):
                ii=torch.tensor(input_id[start : start + max_batch_size], dtype=torch.long, device=device)
                im=torch.tensor(atten_mask[start : start + max_batch_size], dtype=torch.float, device=device)
                si=torch.tensor(segment_id[start : start + max_batch_size], dtype=torch.long, device=device)
                outputs = plm_model(ii,im)[0]#.squeeze()
                store_arr.append(outputs)
            else:
                ii=torch.tensor(input_id[start : len(input_id)], dtype=torch.long, device=device)
                im=torch.tensor(atten_mask[start : len(input_id)], dtype=torch.float, device=device)
                si=torch.tensor(segment_id[start : len(input_id)], dtype=torch.long, device=device)
                outputs = plm_model(ii,im)[0]#.squeeze()
                store_arr.append(outputs)
            #print(outputs.size())
            start+=max_batch_size
    assert len(store_arr)>0
    if len(store_arr)==1:
        outputs=store_arr[0]
    else:
        outputs=store_arr[0]
        #print(outputs.size())
        for t in store_arr[1:]:
            #print(t.size())
            outputs= torch.cat((outputs, t), dim=0)
    q_tab_mat = outputs.new_zeros(len(raw_question_toks),len(table_names))

    old_tables = outputs.masked_select(torch.tensor(table_mask_plm, dtype=torch.bool, device=device).unsqueeze(-1).unsqueeze(0).repeat(outputs.size(0),1,1)).view(outputs.size(0),len(table_id), hidden_size)
   
    start=0
    new_table_arr = []
    maybe_use=[]
    for i,sub_len in enumerate(table_word_len):
        curr=old_tables[:, start:start+sub_len]
        new_table_arr.append(agg(curr))
        maybe_use.append(curr)
        start+=sub_len
    new_tables = torch.cat(new_table_arr, 1)
    tbl_cmp=new_tables[0:1] 
    tbl_msk=new_tables[1:] 
    assert tbl_msk.size(0) == len(raw_question_toks)
    for i in range(len(table_word_len)):
        a=tbl_cmp[:,i] #1,hidden
        b=tbl_msk[:,i] #qu_len,hidden
        #maybe_use[i] qu_len,sublen,hidden
        dis=F.pairwise_distance(a,b,p=2)
        q_tab_mat[:,i]=dis
        # for m in range(maybe_use[i].size(1)):
        #     tmp=maybe_use[i][1:,m]
        #     pre_dis=F.pairwise_distance(a,tmp,p=2) #qu_len
        #     for k in range(pre_dis.size(0)):
        #         if pre_dis[k]>q_tab_mat[k,i]:
        #             q_tab_mat[k,i]=pre_dis[k]

            
            #q_tab_mat[:,i]=pre_dis
    #print(q_tab_mat.transpose(0,1).size())
    #print(q_tab_mat.transpose(0,1).cpu().detach().numpy())
    print(q_tab_mat.transpose(0,1))
    

   
    
    q_col_mat = outputs.new_zeros(len(raw_question_toks),len(column_names))

    old_columns = outputs.masked_select(torch.tensor(column_mask_plm, dtype=torch.bool, device=device).unsqueeze(-1).unsqueeze(0).repeat(outputs.size(0),1,1)).view(outputs.size(0),exact_column_token, hidden_size)
    new_column_arr = []
    start=0
    maybe_use=[]
    for i,sub_len in enumerate(column_word_len):
        curr=old_columns[:,start:start+sub_len]
        new_column_arr.append(agg(curr))
        maybe_use.append(curr)
        start+=sub_len
    new_column = torch.cat(new_column_arr, 1)
    
    col_cmp=new_column[0:1] 
    col_msk=new_column[1:] 
    assert col_msk.size(0) == len(raw_question_toks)
    for i in range(len(column_word_len)):
        a=col_cmp[:,i]
        b=col_msk[:,i]
        dis=F.pairwise_distance(a,b,p=2)
        q_col_mat[:,i]=dis
        # for m in range(maybe_use[i].size(1)):
        #     tmp=maybe_use[i][1:,m]
        #     pre_dis=F.pairwise_distance(a,tmp,p=2) #qu_len
        #     for k in range(pre_dis.size(0)):
        #         if pre_dis[k]>q_col_mat[k,i]:
        #             q_col_mat[k,i]=pre_dis[k]
        #print(dis)
    #print(q_col_mat.transpose(0,1).size()) 
    #print(q_col_mat.transpose(0,1).cpu().detach().numpy())
    print(q_col_mat.transpose(0,1))

    use_matrix = torch.cat([q_tab_mat,q_col_mat], dim=1)
    matrix_min=torch.min(use_matrix)
    #print(matrix_min)
    matrix_max=torch.max(use_matrix)
    #print(matrix_max)
    matrix_mean=torch.mean(use_matrix)
    #print(matrix_mean)
    matrix_var=torch.sqrt(torch.mean(use_matrix))
    #print(matrix_var)
    use_matrix=(use_matrix-matrix_min)/(matrix_max-matrix_min)
    #use_matrix=(use_matrix-matrix_mean)/matrix_var
    #print(use_matrix.size())
    #print(use_matrix)
    

    # vegetables = table_names+column_names
    # farmers = raw_question_toks

    vegetables = raw_question_toks
    farmers = table_names+column_names

    harvest = np.around(use_matrix.cpu().detach().numpy(),3)
    print()
    fig, ax = plt.subplots(figsize=(15,15))
    im = ax.imshow(harvest,cmap="YlGn")
    #threshold = im.norm(use_matrix.max())/2
    # We want to show all ticks...
    ax.set_xticks(np.arange(len(farmers)))
    ax.set_yticks(np.arange(len(vegetables)))
    # ... and label them with the respective list entries
    ax.set_xticklabels(farmers)
    ax.set_yticklabels(vegetables)

    # Rotate the tick labels and set their alignment.
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right",
             rotation_mode="anchor")

    # Loop over data dimensions and create text annotations.
    for i in range(len(vegetables)):
        for j in range(len(farmers)):
            text = ax.text(j, i, harvest[i, j],
                           ha="center", va="center", color="w")

    ax.set_title("Probing Matrix")
    fig.tight_layout()
    plt.show()
    plt.savefig('1.jpg')


