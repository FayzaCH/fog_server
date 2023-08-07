-- ============================
--     CoS table definition
-- ============================

drop table if exists cos;
create table cos (
	id integer primary key,
  	name text not null unique,
    max_response_time real,
    min_concurrent_users real,
    min_requests_per_second real,
    min_bandwidth real,
    max_delay real,
    max_jitter real,
    max_loss_rate real,
    min_cpu integer,
    min_ram real,
    min_disk real
);

-- =================================
--     Requests table definition
-- =================================

create table if not exists requests (
	id text not null,
    src text not null,
  	cos_id integer not null,
    data blob,
    result blob,
    host text,
    path text,
    state integer,
    hreq_at real,
    dres_at real,

    primary key (id, src),

    constraint fk_cos
    foreign key (cos_id)  
    references cos (id)  
);

-- =================================
--     Attempts table definition    
-- =================================

create table if not exists attempts (
	req_id text not null,
    src text not null,
  	attempt_no integer not null,
    host text,
    path text,
    state integer,
    hreq_at real,
    hres_at real,
    rres_at real,
    dres_at real,

    primary key (req_id, src, attempt_no),

    constraint fk_req
    foreign key (req_id, src)  
    references requests (id, src)
);

-- ==================================
--     Responses table definition    
-- ==================================

create table if not exists responses (
	req_id text not null,
    src text not null,
  	attempt_no integer not null,
    host text not null,
    algorithm text,
    cpu real,
    ram real,
    disk real,
    timestamp real,

    primary key (req_id, src, attempt_no, host),

    constraint fk_req
    foreign key (req_id, src)  
    references requests (id, src),

    constraint fk_att
    foreign key (req_id, src, attempt_no)
    references attempts (req_id, src, attempt_no)
);

-- ==============================
--     Paths table definition    
-- ==============================

create table if not exists paths (
	req_id text not null,
    src text not null,
  	attempt_no integer not null,
    host text not null,
    path text not null,
    algorithm text,
    bandwidths text,
    delays text,
    jitters text,
    loss_rates text,
    weight_type text,
    weight real,
    timestamp real,

    primary key (req_id, src, attempt_no, host, path),

    constraint fk_req
    foreign key (req_id, src)  
    references requests (id, src),

    constraint fk_att
    foreign key (req_id, src, attempt_no)
    references attempts (req_id, src, attempt_no)

    constraint fk_res
    foreign key (req_id, src, attempt_no, host)
    references responses (req_id, src, attempt_no, host)
);
