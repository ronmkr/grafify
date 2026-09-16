"""Unit test suite for Redux Toolkit (RTK) and RTK Query (RTKQ) architectural extractor (Phase 15)."""
from __future__ import annotations

from pathlib import Path

from graph_fy.extractors.base import _make_id
from graph_fy.extractors.rtk import (
    extract_rtk,
    is_rtk_file,
    resolve_rtk_backend_edges,
)
from graph_fy.lint import check_rtk_cache_and_state, run_lint


def test_is_rtk_file(tmp_path: Path):
    non_rtk = tmp_path / "utils.ts"
    non_rtk.write_text("export const add = (a: number, b: number) => a + b;")
    assert not is_rtk_file(non_rtk)

    slice_file = tmp_path / "userSlice.ts"
    slice_file.write_text("""
    import { createSlice } from '@reduxjs/toolkit';
    export const userSlice = createSlice({
        name: 'user',
        initialState: { name: '' },
        reducers: {
            setName: (state, action) => { state.name = action.payload; }
        }
    });
    """)
    assert is_rtk_file(slice_file)

    api_file = tmp_path / "api.ts"
    api_file.write_text("""
    import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
    export const api = createApi({
        reducerPath: 'api',
        endpoints: (builder) => ({})
    });
    """)
    assert is_rtk_file(api_file)


def test_extract_rtk_slice_and_actions(tmp_path: Path):
    slice_file = tmp_path / "counterSlice.ts"
    slice_file.write_text("""
    import { createSlice, PayloadAction } from '@reduxjs/toolkit';

    export const counterSlice = createSlice({
        name: 'counter',
        initialState: { value: 0 },
        reducers: {
            increment: (state) => { state.value += 1; },
            decrement: (state) => { state.value -= 1; },
            incrementByAmount: (state, action: PayloadAction<number>) => {
                state.value += action.payload;
            }
        }
    });
    """)
    res = extract_rtk(slice_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    edges = res["edges"]

    slice_id = _make_id("rtk_slice", "counter")
    assert slice_id in nodes
    assert nodes[slice_id]["label"] == "RTK:Slice:counter"

    inc_id = _make_id("rtk_action", "counter", "increment")
    dec_id = _make_id("rtk_action", "counter", "decrement")
    by_amt_id = _make_id("rtk_action", "counter", "incrementByAmount")

    assert inc_id in nodes
    assert dec_id in nodes
    assert by_amt_id in nodes

    # Check defines_action edges
    actions_defined = [
        e["target"] for e in edges
        if e["source"] == slice_id and e["relation"] == "defines_action"
    ]
    assert inc_id in actions_defined
    assert dec_id in actions_defined


def test_extract_rtk_thunk(tmp_path: Path):
    thunk_file = tmp_path / "userThunks.ts"
    thunk_file.write_text("""
    import { createAsyncThunk } from '@reduxjs/toolkit';

    export const fetchUserById = createAsyncThunk(
        'users/fetchById',
        async (userId: number) => {
            const response = await fetch(`/api/users/${userId}`);
            return await response.json();
        }
    );
    """)
    res = extract_rtk(thunk_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    edges = res["edges"]

    thunk_id = _make_id("rtk_thunk", "users/fetchById")
    assert thunk_id in nodes
    assert nodes[thunk_id]["label"] == "RTK:Thunk:users/fetchById"

    # Check lifecycle actions emitted
    pending_id = _make_id("rtk_action", "users/fetchById", "pending")
    fulfilled_id = _make_id("rtk_action", "users/fetchById", "fulfilled")
    rejected_id = _make_id("rtk_action", "users/fetchById", "rejected")

    assert pending_id in nodes
    assert fulfilled_id in nodes
    assert rejected_id in nodes

    emitted = [e["target"] for e in edges if e["source"] == thunk_id and e["relation"] == "emits_action"]
    assert pending_id in emitted
    assert fulfilled_id in emitted
    assert rejected_id in emitted


def test_extract_rtk_store(tmp_path: Path):
    store_file = tmp_path / "store.ts"
    store_file.write_text("""
    import { configureStore } from '@reduxjs/toolkit';

    export const store = configureStore({
        reducer: {
            users: usersReducer,
            posts: postsReducer
        }
    });
    """)
    res = extract_rtk(store_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    edges = res["edges"]

    store_id = _make_id("rtk_store", "store")
    assert store_id in nodes
    manages_targets = [
        e["target"] for e in edges
        if e["source"] == store_id and e["relation"] == "manages_slice"
    ]
    assert _make_id("rtk_slice", "users") in manages_targets
    assert _make_id("rtk_slice", "posts") in manages_targets


def test_extract_rtkq_api_and_cache_invalidation(tmp_path: Path):
    api_file = tmp_path / "apiSlice.ts"
    api_file.write_text("""
    import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

    export const apiSlice = createApi({
        reducerPath: 'api',
        baseQuery: fetchBaseQuery({ baseUrl: '/api' }),
        tagTypes: ['Posts', 'Users'],
        endpoints: (builder) => ({
            getPosts: builder.query({
                query: () => '/posts',
                providesTags: ['Posts']
            }),
            getUserById: builder.query({
                query: (id) => `/users/${id}`,
                providesTags: ['Users']
            }),
            addPost: builder.mutation({
                query: (body) => ({
                    url: '/posts',
                    method: 'POST',
                    body
                }),
                invalidatesTags: ['Posts']
            }),
            updateUser: builder.mutation({
                query: ({ id, ...patch }) => ({
                    url: `/users/${id}`,
                    method: 'PUT',
                    body: patch
                }),
                invalidatesTags: ['Users']
            })
        })
    });
    """)
    res = extract_rtk(api_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    edges = res["edges"]

    api_id = _make_id("rtkq_api", "api")
    assert api_id in nodes
    api_node = nodes[api_id]
    assert api_node["tag_types"] == ["Posts", "Users"]

    # Endpoints
    get_posts_id = _make_id("rtkq_query", "api", "getPosts")
    get_user_id = _make_id("rtkq_query", "api", "getUserById")
    add_post_id = _make_id("rtkq_mutation", "api", "addPost")
    update_user_id = _make_id("rtkq_mutation", "api", "updateUser")

    assert get_posts_id in nodes
    assert get_user_id in nodes
    assert add_post_id in nodes
    assert update_user_id in nodes

    # Auto-generated React hooks
    hook_get_posts = _make_id("rtkq_hook", "useGetPostsQuery")
    hook_get_user = _make_id("rtkq_hook", "useGetUserByIdQuery")
    hook_add_post = _make_id("rtkq_hook", "useAddPostMutation")
    hook_update_user = _make_id("rtkq_hook", "useUpdateUserMutation")

    assert hook_get_posts in nodes
    assert hook_get_user in nodes
    assert hook_add_post in nodes
    assert hook_update_user in nodes

    # Cache invalidation edge
    inv_edges = [
        e for e in edges if e["relation"] == "invalidates_cache"
    ]
    assert any(
        e["source"] == add_post_id and e["target"] == get_posts_id
        for e in inv_edges
    )
    assert any(
        e["source"] == update_user_id and e["target"] == get_user_id
        for e in inv_edges
    )


def test_extract_selectors_and_components(tmp_path: Path):
    comp_file = tmp_path / "UserProfile.tsx"
    comp_file.write_text("""
    import React from 'react';
    import { useSelector, useDispatch } from 'react-redux';
    import { useGetUserByIdQuery } from './apiSlice';
    import { setUserName } from './userSlice';

    export function UserProfile() {
        const user = useSelector((state) => state.users);
        const { data } = useGetUserByIdQuery(1);
        const dispatch = useDispatch();

        const handleClick = () => {
            dispatch(setUserName('Alice'));
        };

        return <div>{user.name}</div>;
    }
    """)
    res = extract_rtk(comp_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    edges = res["edges"]

    comp_id = _make_id("component", "UserProfile")
    assert comp_id in nodes

    # Hook usage
    hook_id = _make_id("rtkq_hook", "useGetUserByIdQuery")
    hook_uses = [
        e["target"] for e in edges
        if e["source"] == comp_id and e["relation"] == "uses_hook"
    ]
    assert hook_id in hook_uses

    # Selector
    sel_id = _make_id("rtk_selector", "users")
    selector_uses = [
        e["target"] for e in edges
        if e["source"] == comp_id and e["relation"] == "uses_selector"
    ]
    assert sel_id in selector_uses

    # Dispatches action
    dispatch_edges = [
        e for e in edges
        if e["source"] == comp_id and e["relation"] == "dispatches_action"
    ]
    assert any(e.get("action_name") == "setUserName" for e in dispatch_edges)


def test_cross_resolve_rtk_backend_edges():
    nodes = [
        {
            "id": "rtkq_query_api_getPosts",
            "type": "rtkq_query",
            "url_path": "/posts",
            "http_method": "GET",
        },
        {
            "id": "rtkq_mutation_api_addPost",
            "type": "rtkq_mutation",
            "url_path": "/posts",
            "http_method": "POST",
        },
        {
            "id": "openapi_op_get_posts",
            "type": "openapi_operation",
            "path": "/posts",
            "http_method": "GET",
        },
        {
            "id": "openapi_op_create_post",
            "type": "openapi_operation",
            "path": "/posts",
            "http_method": "POST",
        },
    ]
    edges = []
    new_edges = resolve_rtk_backend_edges(nodes, edges)

    assert len(new_edges) == 2
    edge_pairs = {(e["source"], e["target"], e["relation"]) for e in new_edges}
    assert ("rtkq_query_api_getPosts", "openapi_op_get_posts", "fetches_from") in edge_pairs
    assert ("rtkq_mutation_api_addPost", "openapi_op_create_post", "fetches_from") in edge_pairs


def test_check_rtk_cache_linting():
    nodes = [
        {
            "id": "rtkq_api_main",
            "type": "rtkq_api",
            "tag_types": ["Users"],
        },
        {
            "id": "rtkq_query_get_posts",
            "type": "rtkq_query",
            "endpoint_name": "getPosts",
            "provides_tags": ["UnregisteredTag"],
        },
        {
            "id": "rtkq_mutation_delete_comment",
            "type": "rtkq_mutation",
            "endpoint_name": "deleteComment",
            "invalidates_tags": ["OrphanedTag"],
        },
    ]
    edges = [
        {"source": "rtkq_api_main", "target": "rtkq_query_get_posts", "relation": "declares_endpoint"},
        {"source": "rtkq_api_main", "target": "rtkq_mutation_delete_comment", "relation": "declares_endpoint"},
    ]

    findings = check_rtk_cache_and_state(nodes, edges)
    rules = [f["rule"] for f in findings]

    assert "rtk_undeclared_cache_tag" in rules
    assert "rtk_orphaned_mutation_tag" in rules

    # Test integration in run_lint
    lint_report = run_lint({"nodes": nodes, "edges": edges}, check_orphans=False)
    assert any(f["rule"] == "rtk_undeclared_cache_tag" for f in lint_report["findings"])
